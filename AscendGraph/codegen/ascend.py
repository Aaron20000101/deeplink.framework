import torch
import math
import textwrap
import contextlib

from typing import Any
from torch.fx.node import Node
from io import StringIO


graph_id = 0

need_node = ['add', 'mul', 'div', 'view', 'scatter',
             'where', 'convolution', 'le', 'scalar_tensor']

def get_graph_id():
    global graph_id
    graph_id = graph_id + 1
    return graph_id


class CodeBlock:
    tabwidth = 4

    def __init__(self, backend='', indent=0, lang=''):
        self._lines = []
        self._indent = indent
        self._backend = backend
        self._lang = lang

    def get_str(
        self,
    ):
        buf = StringIO()
        for line in self._lines:
            assert isinstance(line, str)
            buf.write(line)
            if self._lang == 'cpp' or self._lang == 'c':
                buf.write(";")
            buf.write("\n")
        return buf.getvalue()

    def clear(self):
        self._lines.clear()

    def __bool__(self):
        return bool(self._lines)

    def prefix(self):
        return " " * (self._indent * self.tabwidth)

    def add_line(self, line):
        if line.strip():
            self._lines.append(f"{self.prefix()}{line}")
        else:
            self._lines.append("")

    def add_lines(self, lines):
        for line in lines:
            self.add_line(line)

    def indent(self, offset=1):
        @contextlib.contextmanager
        def ctx():
            self._indent += offset
            yield
            self._indent -= offset

        return ctx()

    def splice(self, other_code, dedent=False):
        if isinstance(other_code, CodeBlock):
            _dedent = float("inf")
            if dedent:
                for line in other_code._lines:
                    if line:
                        _dedent = min(_dedent, len(line) - len(line.lstrip()))
            if math.isinf(_dedent):
                _dedent = 0
            for line in other_code._lines:
                CodeBlock.add_line(self, line[_dedent:])
        else:
            if dedent:
                other_code = textwrap.dedent(other_code)
            other_code = other_code.lstrip()
            other_code = other_code.rstrip()
            if not other_code:
                return
            for line in other_code.split("\n"):
                self.add_line(line)


def process_name(name, target):
    if hasattr(target, "name"):
        real_op = target.name().split('::')[-1]
        if real_op.find('.') != -1:
            real_op = real_op.split('.')[0]
    else:
        real_op = name.rsplit('_', 1)[0] if name[-1].isdigit() else name

    return real_op


class AscendCodegen(torch.fx.Interpreter):
    def __init__(self, graph):

        self.graph = graph
        self.override = AscendOverrides

        self.import_code = CodeBlock()
        self.build_graph_code = CodeBlock(indent=1, lang='cpp')

        self.graph_id = str(get_graph_id())
        self.args_dict = {}
        self.input_args = []
        self.output_args = []

        super().__init__(graph)

    def placeholder(self, name, target, args, kwargs):
        self.args_dict[name] = 'op' + str(len(self.args_dict))
        self.input_args.append(self.cur_node)

        fake_tensor = self.cur_node.meta['val']
        tensor_shape = '{' + ','.join(list(map(str, fake_tensor.shape))) + '}'
        self.build_graph_code.add_line(f'std::vector<int64_t> {self.args_dict[name]}_tensor_shape{tensor_shape};')
        
        tensor_format = "FORMAT_NCHW"
        ascend_dtype = get_ascend_dtype(fake_tensor.dtype)
        src_code = f'TensorDesc {self.args_dict[name]}_tensor_desc_data_op = TensorDesc(ge::Shape({self.args_dict[name]}_tensor_shape), {tensor_format}, {ascend_dtype});\n'
        src_code += f'auto {self.args_dict[name]} = op::Data("{self.args_dict[name]}");\n'
        src_code += f'{self.args_dict[name]}.update_input_desc_x({self.args_dict[name]}_tensor_desc_data_op);\n'
        src_code += f'{self.args_dict[name]}.update_output_desc_y({self.args_dict[name]}_tensor_desc_data_op);\n'
        src_code += f'graph.AddOp({self.args_dict[name]});\n'
        src_code += f'graph_inputs.push_back({self.args_dict[name]});\n'
        self.build_graph_code.splice(src_code)

    def call_function(self, name, target, args, kwargs):
        if name not in self.args_dict.keys():
            self.args_dict[name] = 'op' + str(len(self.args_dict))

        arg_code, args_list = AscendOverrides.gen_args(self.args_dict[name], self.args_dict, self.cur_node, args)

        real_op = process_name(name, target)
        op_code = getattr(self.override, real_op)(*args_list)
        self.build_graph_code.splice(arg_code)
        self.build_graph_code.splice(op_code)

    def call_method(self, name, target, args, kwargs):
        pass

    def output(self, name, target, args, kwargs):
        for arg in args:
            self.output_args.extend(arg)

    def run_node(self, n : Node) -> Any:
        self.cur_node = n
        op = n.op
        name = n.name
        target = n.target
        args = n.args
        kwargs = n.kwargs

        assert isinstance(args, tuple)
        assert isinstance(kwargs, dict)

        return getattr(self, op)(name, target, args, kwargs) 

    def codegen(self):
        self.run()
        return self.generate_code()

    def gen_build_graph_code(self):
        graph_code = CodeBlock(indent=1)
        graph_code.add_lines(
            [
                f'std::vector<Operator> graph_inputs;'
                f'std::vector<Operator> graph_outputs;'
            ]
        )

        graph_code.splice(self.build_graph_code, dedent=True)
        
        output_str = []
        self.output_names = []
        for node in self.output_args:
            if isinstance(node, torch.fx.node.Node):
                name = self.args_dict[node.name]
                self.output_names.append(name)
                output_str.append(f'graph_outputs.push_back({name});')
            else:
                self.output_names.append(str(node))

        graph_code.add_lines(output_str)
        graph_code.add_line(f'graph.SetInputs(graph_inputs).SetOutputs(graph_outputs);');
        graph_code.add_line(f'return 0;')

        return graph_code

    def get_kernel_header(self):
        return f"""
                #include "graph_utils.h"
                #include <iostream>
                #include <fstream>
                #include <string.h>
                #include <stdint.h>
                #include <memory>
                #include <numeric>
                #include <functional>
               """

    def gen_import_code(self):
        self.import_code.splice(
            f"""
                from ctypes import c_void_p, c_long
                import torch
                import random
                from torch import empty_strided, as_strided, device
                from third_party.DICP.AscendGraph.compile import AsyncCompileAscend
                
                aten = torch.ops.aten
                assert_size_stride = torch._C._dynamo.guards.assert_size_stride
            """
            , dedent=True
        )
        return self.import_code.get_str()

    def gen_call_func(self):
        # TODO check scalar input
        call_body = CodeBlock(indent=1)
        self.args = []
        for i in range(len(self.input_args)):
            self.args.append('arg' + str(i))
        
        call_body.add_line(f"({','.join(self.args)}) = args")
        call_body.add_line(f"inputs_data = list(map(lambda x: x.data_ptr(), args))")
        call_body.add_line(f"args.clear()")

        unique_output_names = []
        call_str = [f'output_np = kernel_cpp_0(inputs_data)']
        for name in self.output_names:
            if name != 'None':
                if name not in unique_output_names:
                    unique_output_names.append(name)
                else:
                    continue
                index = len(unique_output_names) - 1
                call_str.append(f'{name} = torch.from_numpy(output_np[{index}])')

        call_body.add_lines(call_str)
        del_args = [f'del ' + x for x in self.args]
        call_body.add_lines(del_args)
        call_body.add_line(f"return ({', '.join(self.output_names)})")

        call_func = CodeBlock()
        call_func.add_line(f"def call(args):")
        call_func.splice(call_body)
 
        return call_func.get_str()

    def gen_main_func(self):
        main_body = CodeBlock(indent=1)
        main_body.splice(
            f"""
                from torch._dynamo.testing import rand_strided
                from torch._inductor.utils import print_performance
            """
            , dedent=True
        )

        py_rand_inputs = []
        for i in range(len(self.input_args)):
            node = self.input_args[i]
            name = self.args[i]
            val = node.meta['val']
            shape = str(tuple(val.size()))
            stride = str(tuple(val.stride()))
            device = val.device.type
            dtype = str(val.dtype)
            code_str = f'''{name} = rand_strided({shape}, {stride}, device='{device}', dtype={dtype})'''
            py_rand_inputs.append(code_str)
        main_body.add_lines(py_rand_inputs)
        main_body.add_line(f"print_performance(lambda: call([{', '.join(self.args)}]))")

        main_func = CodeBlock()
        main_func.add_line(f"""if __name__ == "__main__":""")
        main_func.splice(main_body)
        return main_func.get_str()

    def gen_compile_func_code(self):
        compile_func_body = CodeBlock(indent=1)
        compile_func_body.splice(
            f"""
                std::string graph_name = "BuildGraph" + graph_id;
                Graph graph(graph_name.c_str());
                Status ret = genGraph(graph);
                if (ret != SUCCESS) {{
                    std::cout << "Generate simple graph failed."<<std::endl;
                    return FAILED;
                }}
                std::cout<<"Generate simple graph success."<<std::endl;
                
                AclgraphBuilder builder;
                builder.saveGraph(graph_path, graph);
                std::cout << "graph path: " << graph_path << std::endl;
                return SUCCESS;
            """
            , dedent=True
        )
        compile_func = CodeBlock()
        compile_func.add_line(f'extern "C" int compile(char* graph_path) {{')
        compile_func.splice(compile_func_body)
        compile_func.splice(f"""}}
                                ''')""")

        return compile_func

    def gen_compile_graph_code(self):
        compile_graph_code = CodeBlock()
        compile_graph_code.splice(
            f"""
                async_compile = AsyncCompileAscend()
                kernel_cpp_0 = async_compile.ascend('''
            """
            , dedent=True
        )
        compile_graph_code.splice(self.get_kernel_header(), dedent=True)
        src_code = f'uint32_t graph_id = {self.graph_id};\n'
        src_code += f'int32_t genGraph(Graph& graph) {{\n'
        compile_graph_code.splice(src_code)
        
        compile_graph_code.splice(self.gen_build_graph_code())
        compile_graph_code.add_line(f'}}')

        compile_graph_code.splice(self.gen_compile_func_code())
        compile_graph_code.add_line('async_compile.wait(globals())')
        compile_graph_code.add_line('del async_compile')

        return compile_graph_code.get_str()

    def generate_code(self):
        return (self.gen_import_code() + self.gen_compile_graph_code()+ self.gen_call_func() + self.gen_main_func())


def get_ascend_dtype(dtype: torch.dtype) -> str:
    if dtype == torch.int64:
        return "ge::DataType::DT_INT64"
    elif dtype == torch.float32:
        return "ge::DataType::DT_FLOAT"
    elif dtype == torch.int32:
        return "ge::DataType::DT_INT32"
    else:
        raise RuntimeError("unknow torch data tyep type in get_ascend_dtype!")


def get_cpp_dtype(dtype: torch.dtype) -> str:
    if dtype == torch.int64:
        return "int64_t"
    elif dtype == torch.float32:
        return "float"
    else:
        raise RuntimeError("unknow torch data tyep type in get_cpp_dtype!")


class AscendOverrides:
    @staticmethod
    def gen_args(op_var, args_dict, node, args):
        src_code = CodeBlock()
        args_str = [op_var]
        count = 0
        for i in range(len(args)):
            if isinstance(args[i], Node):
                args_str.append(args_dict[args[i].name])
            elif isinstance(args[i], bool):
                args_str.append(str(args[i]).lower())
            elif isinstance(args[i], torch.fx.immutable_collections.immutable_list):
                args_str.append(str(args[i]).replace('[', '{').replace(']', '}'))
            elif isinstance(args[i], torch.dtype):
                in_shape_size = '{' + str(node.meta['val'].shape).split('[')[-1].split(']')[0] + '}'
                src_code.add_line(f'std::vector<int64_t> {op_var}_shape{count}{in_shape_size};')
                args_str.append(f'{op_var}_type{count}')
                count += 1
            else:
                args_str.append(str(args[i]))

        if process_name(node.name, node.target) in need_node:
            args_str.append(node)

        return src_code, args_str

    @staticmethod
    def mul(name, x, y, node):
        (x_node, y_node) = node.args
        if isinstance(y_node, torch.fx.node.Node):
            src_code = f"""auto {name} = op::Mul("{name}")
                             .set_input_x1({x})
                             .set_input_x2({y});
                           graph.AddOp({name});"""
        else:
            # y is scalar
            dtype = node.meta['val'].dtype
            cpp_dtype = get_cpp_dtype(dtype)
            ascend_dtype = get_ascend_dtype(dtype)
            src_code = f"""{cpp_dtype} {name}_scalar_value = static_cast<{cpp_dtype}>({y});
                           auto {name}_scalar_tensor = genTensor(std::vector<int64_t>(), FORMAT_NCHW, {ascend_dtype});
                           setTensorData({name}_scalar_tensor, reinterpret_cast<uint8_t*>(&{name}_scalar_value), sizeof({cpp_dtype}), "{name} scalar");
                           auto {name}_scalar = op::Const("{name}_scalar")
                             .set_attr_value({name}_scalar_tensor);
                           auto {name} = op::Mul("{name}")
                             .set_input_x1({x})
                             .set_input_x2({name}_scalar);
                           graph.AddOp({name}_scalar);
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def add(name, x, y, node):
        (x_node, y_node) = node.args
        if isinstance(y_node, torch.fx.node.Node):
            src_code = f"""auto {name} = op::AddV2("{name}")
                             .set_input_x1({x})
                             .set_input_x2({y});
                           graph.AddOp({name});"""
        else:
            # y is scalar
            dtype = node.meta['val'].dtype
            cpp_dtype = get_cpp_dtype(dtype)
            ascend_dtype = get_ascend_dtype(dtype)
            src_code = f"""{cpp_dtype} {name}_scalar_value = static_cast<{cpp_dtype}>({y});
                           auto {name}_scalar_tensor = genTensor(std::vector<int64_t>(), FORMAT_NCHW, {ascend_dtype});
                           setTensorData({name}_scalar_tensor, reinterpret_cast<uint8_t*>(&{name}_scalar_value), sizeof({cpp_dtype}), "{name} scalar");
                           auto {name}_scalar = op::Const("{name}_scalar")
                             .set_attr_value({name}_scalar_tensor);
                           auto {name} = op::AddV2("{name}")
                             .set_input_x1({x})
                             .set_input_x2({name}_scalar);
                           graph.AddOp({name}_scalar);
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def sub(name, x, y):
        src_code = f"""auto {name} = op::Sub("{name}")
                         .set_input_x1({x})
                         .set_input_x2({y});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def relu(name, x):
        src_code = f"""auto {name} = op::Relu("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def reciprocal(name, x):
        src_code = f"""auto {name} = op::Reciprocal("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def sqrt(name, x):
        src_code = f"""auto {name} = op::Sqrt("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def rsqrt(name, x):
        src_code = f"""auto {name} = op::Rsqrt("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def convolution(name, input, weight, bias, stride, padding,
                    dilation, transposed, output_padding, groups, node):
        assert transposed == 'false'
        assert output_padding == '{0, 0}'
        stride = stride.split('{')[-1].split('}')[0].split(', ')
        padding = padding.split('{')[-1].split('}')[0].split(', ')
        dilation = dilation.split('{')[-1].split('}')[0].split(', ')
        
        if len(stride) == 2:
            real_stride = [1, 1, stride[0], stride[1]]
            stride_str = '{' + ', '.join(map(str, real_stride)) + '}'
        else:
            stride_str = '{' + ', '.join(map(str, stride)) + '}'

        if len(padding) == 2:
            real_padding = [padding[0], padding[0], padding[1], padding[1]]
            padding_str = '{' + ', '.join(map(str, real_padding)) + '}'
        else:
            padding_str = '{' + ', '.join(map(str, padding)) + '}'

        if len(dilation) == 2:
            real_dialtion = [dilation[0], dilation[0], dilation[1], dilation[1]]
            dilation_str = '{' + ', '.join(map(str, real_dialtion)) + '}'
        else:
            dilation_str = '{' + ', '.join(map(str, dilation)) + '}'

        
        format = "NCHW" if node.meta['val'].stride()[-1] == 1 else "NHWC"
        src_code = f"""auto {name} = op::Conv2D("{name}")
                         .set_input_x({input})
                         .set_input_filter({weight})
                         .set_attr_strides({stride_str})
                         .set_attr_pads({padding_str})
                         .set_attr_dilations({dilation_str})
                         .set_attr_groups({groups})
                         .set_attr_data_format("{format}");"""

        if bias != 'None':
            src_code += f'{name}.set_input_bias({bias});\n'
        src_code += f'graph.AddOp({name});\n'
        return src_code

    @staticmethod
    def convert_element_type(name, x, torch_dtype):
        ascend_dtype = get_ascend_dtype(torch_dtype)
        src_code = f"""auto {name} = op::Cast("{name}")
                         .set_input_x({x})
                         .set_attr_dst_type({ascend_dtype});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def mean(name, x, dims='{}', keepdim='false'):
        src_code = f"""std::vector<int> {name}_axes_value {dims};
                       std::vector<int64_t> {name}_axes_tensor_shape;
                       if ({name}_axes_value.size() != 0) {{
                         {name}_axes_tensor_shape.push_back({name}_axes_value.size());
                       }}
                       auto {name}_axes_tensor = genTensor({name}_axes_tensor_shape, FORMAT_ND, DT_INT32);
                       setTensorData({name}_axes_tensor, reinterpret_cast<uint8_t*>({name}_axes_value.data()), {name}_axes_value.size() * sizeof(int), "{name}_axes");
                       auto {name}_axes = op::Const("{name}_axes")
                         .set_attr_value({name}_axes_tensor);
                       auto {name} = op::ReduceMean("{name}")
                         .set_input_x({x})
                         .set_input_axes({name}_axes)
                         .set_attr_keep_dims({keepdim});
                       graph.AddOp({name}_axes);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def view(name, x, size, node):
        numel = node.meta['val'].numel()
        shape = list(node.meta['val'].shape)
        if shape.count(-1) > 0:
            prod = 1
            for i in shape:
                if i > 0:
                    prod *= i

            real_shape = []
            for i in shape:
                if i > 0:
                    real_shape.append(str(i))
                else:
                    real_shape.append(str(numel / prod))
            shape_str = '{' + ', '.join(real_shape) + '}'
        else:
            shape = list(map(str, shape))
            shape_str = '{' + ','.join(shape) + '}'

        src_code = f"""auto {name} = op::TransShape("{name}")
                         .set_input_x({x})
                         .set_attr_outShape({shape_str});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def clone(name, x):
        src_code = f"""auto {name} = op::Identity("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def unsqueeze(name, x, dim):
        real_dim_str = dim.replace('[','')
        real_dim_str = real_dim_str.replace(']','')
        real_dim_str = real_dim_str.replace('{','')
        real_dim_str = real_dim_str.replace('}','')
        real_dim_str = '{' + real_dim_str + '}'
        src_code = f"""std::vector<int64_t> {name}_dims{real_dim_str};
                       auto {name} = op::Unsqueeze("{name}")
                         .set_input_x({x})
                         .set_attr_axes({name}_dims);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def squeeze(name, x, dim):
        if dim == '0':
            real_dim_str = dim
        else:
            real_dim_str = dim.replace('[','')
            real_dim_str = real_dim_str.replace(']','')
            real_dim_str = real_dim_str.replace('{','')
            real_dim_str = real_dim_str.replace('}','')
            real_dim_str = '{' + real_dim_str + '}'
        src_code = f"""auto {name} = op::Squeeze("{name}")
                         .set_input_x({x})
                         .set_attr_axis({real_dim_str});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def getitem(name, input, index):
        src_code = f"""auto {name} = op::Identity("{name}")
                         .set_input_x({input}, {index});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def exp(name, x):
        src_code = f"""auto {name} = op::Exp("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def div(name, x, y, node):
        (x_node, y_node) = node.args
        if isinstance(y_node, torch.fx.node.Node):
            src_code = f"""auto {name} = op::DivNoNan("{name}")
                             .set_input_x1({x})
                             .set_input_x2({y});
                           graph.AddOp({name});"""
        else:
            div_value = str(1.0 / y_node)
            src_code = f"""auto {name} = op::Muls("{name}")
                             .set_input_x({x})
                             .set_attr_value({div_value});
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def sum(name, x, axes='{}', keep_dims='false'):
        src_code = f"""std::vector<int64_t> {name}_axes{axes};
                       auto {name} = op::ReduceSumD("{name}")
                         .set_input_x({x})
                         .set_attr_axes({name}_axes)
                         .set_attr_keep_dims({keep_dims});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def amax(name, x, axes, keep_dims):
        src_code = f"""auto {name} = op::ReduceMaxD("{name}")
                         .set_input_x({x})
                         .set_attr_axes({axes})
                         .set_attr_keep_dims({keep_dims});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def permute(name, x, order):
        src_code = f"""auto {name} = op::Permute("{name}")
                         .set_input_x({x})
                         .set_attr_order({order});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def max_pool2d_with_indices(name, x, ksize, strides, padding='{0, 0}'):
        assert len(ksize.split(',')) == 2
        assert len(strides.split(',')) == 2
        ksize_str = '{1 , ' + str(ksize).strip('{}') + ' , 1}'
        strides_str = '{1, ' + str(strides).strip('{}') + ' , 1}'


        if padding != '{0, 0}':
            padding = padding.split('{')[-1].split('}')[0].split(', ')
            padding0 = padding[0]
            padding1 = padding[1]
            padding = f'0, 0, 0, 0, {padding0}, {padding0}, {padding1}, {padding1}'
            src_code = f"""TensorDesc {name}_pad_desc(ge::Shape({{4, 2}}), FORMAT_NCHW, DT_INT32);
                           std::vector<int> {name}_pad_value {{ {padding} }};
                           Tensor {name}_pad_tensor({name}_pad_desc);
                           setTensorData({name}_pad_tensor, reinterpret_cast<uint8_t*>({name}_pad_value.data()), sizeof(int) * 8, "{name} pad");

                           auto {name}_paddings = op::Const("{name}_paddings")
                             .set_attr_value({name}_pad_tensor);
                           graph.AddOp({name}_paddings);
                           auto {name}_pad = op::Pad("{name}_pad")
                             .set_input_x({x})
                             .set_input_paddings({name}_paddings);
                           graph.AddOp({name}_pad);
                           auto {name} = op::MaxPoolWithArgmax("{name}")
                             .set_input_x({name}_pad)
                             .set_attr_ksize({ksize_str})
                             .set_attr_strides({strides_str})
                             .set_attr_padding("VALID");
                           graph.AddOp({name});"""
        else:
            padding = 'VALID'
            src_code = f"""auto {name} = op::MaxPoolWithArgmax("{name}")
                             .set_input_x({x})
                             .set_attr_ksize({ksize_str})
                             .set_attr_strides({strides_str})
                             .set_attr_padding("{padding}");
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def addmm(name, c, a, b, beta='1', alpha='1'):
        src_code = f"""float {name}_beta_value = {beta};
                       float {name}_alpha_value = {alpha};
                       auto {name}_beta_tensor = genTensor(std::vector<int64_t>(), FORMAT_ND, DT_FLOAT);
                       auto {name}_alpha_tensor = genTensor(std::vector<int64_t>(), FORMAT_ND, DT_FLOAT);
                       setTensorData({name}_beta_tensor, reinterpret_cast<uint8_t*>(&{name}_beta_value), sizeof(float), "{name} beta");
                       setTensorData({name}_alpha_tensor, reinterpret_cast<uint8_t*>(&{name}_alpha_value), sizeof(float), "{name} alpha");

                       auto {name}_beta = op::Const("{name}_beta")
                         .set_attr_value({name}_beta_tensor);
                       auto {name}_alpha = op::Const("{name}_alpha")
                         .set_attr_value({name}_alpha_tensor);

                       auto {name}_c_beta = op::Mul("{name}_c_beta")
                         .set_input_x1({c})
                         .set_input_x2({name}_beta);
                       graph.AddOp({name}_c_beta);

                       auto {name}_a_alpha = op::Mul("{name}_a_alpha")
                         .set_input_x1({a})
                         .set_input_x2({name}_alpha);
                       graph.AddOp({name}_a_alpha);

                       auto {name}_matmul = op::MatMul("{name}_matmul")
                         .set_input_x1({name}_a_alpha)
                         .set_input_x2({b});
                       graph.AddOp({name}_matmul);

                       auto {name} = op::AddV2("{name}")
                         .set_input_x1({name}_c_beta)
                         .set_input_x2({name}_matmul);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def var(name, x, axes, correction='1', keepdim='true'):
        if correction == '1':
            unbiased = 'true'
        elif correction == 0:
            unbiased = 'false'
        else:
            raise RuntimeError("not supported yet!")
        
        src_code = f"""// 1. mean
                       std::vector<int> {name}_axes_value {axes};
                       std::vector<int64_t> {name}_axes_tensor_shape;
                       if ({name}_axes_value.size() != 0) {{
                         {name}_axes_tensor_shape.push_back({name}_axes_value.size());
                       }}
                       auto {name}_axes_tensor = genTensor({name}_axes_tensor_shape, FORMAT_ND, DT_INT32);
                       setTensorData({name}_axes_tensor, reinterpret_cast<uint8_t*>({name}_axes_value.data()), {name}_axes_value.size() * sizeof(int), "{name}_axes");
                       auto {name}_axes = op::Const("{name}_axes")
                         .set_attr_value({name}_axes_tensor);
                       auto {name}_mean = op::ReduceMean("{name}_mean")
                         .set_input_x({x})
                         .set_input_axes({name}_axes)
                         .set_attr_keep_dims({keepdim});
                       graph.AddOp({name}_axes);
                       graph.AddOp({name}_mean);
    
                       // 2. broadcast to self
                       auto {name}_input_shape = op::Shape("{name}_input_shape")
                         .set_input_x({x});
                       auto {name}_broadcast_to = op::BroadcastTo("{name}_broadcast_to")
                         .set_input_x({name}_mean)
                         .set_input_shape({name}_input_shape);
                       graph.AddOp({name}_input_shape);
                       graph.AddOp({name}_broadcast_to);
        
                       // 3. ReduceStdV2Update
                       auto {name} = op::ReduceStdV2Update("{name}")
                         .set_input_x({x})
                         .set_input_mean({name}_broadcast_to)
                         .set_attr_dim({axes})
                         .set_attr_unbiased({unbiased})
                         .set_attr_keepdim({keepdim});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def log(name, x):
        src_code = f"""auto {name} = op::Log("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def gather(name, x, dim, index):
        src_code = f"""auto {name}_dim_shape = ge::Shape({{1}});
                       TensorDesc {name}_dim_desc({name}_dim_shape, FORMAT_NCHW, DT_INT32);
                       Tensor {name}_dim_tensor({name}_dim_desc);
                       int {name}_dim_value = {dim};
                       setTensorData({name}_dim_tensor, reinterpret_cast<uint8_t*>(&{name}_dim_value), sizeof(int), "{name}_dim");

                       auto {name}_dim = op::Const("{name}_dim")
                         .set_attr_value({name}_dim_tensor);
                       auto {name} = op::GatherD("{name}")
                         .set_input_x({x})
                         .set_input_dim({name}_dim)
                         .set_input_index({index})
                         .set_attr_dim({dim});
                       graph.AddOp({name}_dim);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def neg(name, x):
        src_code = f"""auto {name} = op::Neg("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def expand(name, x, shape):
        src_code = f"""std::vector<int64_t> {name}_shape{shape};
                       auto {name} = op::ExpandD("{name}")
                         .set_input_x({x})
                         .set_attr_shape({name}_shape);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def zeros_like(name, x, value):
        # TODO(tangzhiyi): ignore kwargs, need to check this
        src_code = f"""auto {name} = op::ZerosLike("{name}")
                         .set_input_x({x});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def scatter(name, var, dim, index, value, node):
        assert(len(node.args) > 3)
        value_node = node.args[3]
        if isinstance(value_node, torch.fx.node.Node):
            src_code = f"""auto {name} = op::ScatterElements("{name}")
                             .set_input_data({var})
                             .set_input_indices({index})
                             .set_input_updates({value})
                             .set_attr_axis({dim});
                           graph.AddOp({name});"""
        else:
            dtype = node.meta['val'].dtype
            ascend_dtype = get_ascend_dtype(dtype)
            cpp_dtype = get_cpp_dtype(dtype)
            src_code = f"""std::vector<int64_t> {name}_value_dims;
                           TensorDesc {name}_value_desc(ge::Shape({name}_value_dims), FORMAT_NCHW, {ascend_dtype});
                           Tensor {name}_value_tensor({name}_value_desc);
                           {cpp_dtype} {name}_value_value = {value};
                           setTensorData({name}_value_tensor, reinterpret_cast<uint8_t*>(&{name}_value_value), sizeof({cpp_dtype}), "{name}_value");

                           auto {name}_value = op::Const("{name}_value")
                             .set_attr_value({name}_value_tensor);
                           auto {name}_index_shape = op::Shape("{name}_index_shape")
                             .set_input_x({index});
                           auto {name}_value_bcast = op::BroadcastTo("{name}_value_bcast")
                             .set_input_x({name}_value)
                             .set_input_shape({name}_index_shape);
                           auto {name} = op::ScatterElements("{name}")
                             .set_input_data({var})
                             .set_input_indices({index})
                             .set_input_updates({name}_value_bcast)
                             .set_attr_axis({dim});
                           graph.AddOp({name}_value);
                           graph.AddOp({name}_index_shape);
                           graph.AddOp({name}_value_bcast);
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def mm(name, x, y):
        src_code = f"""auto {name} = op::MatMul("{name}")
                         .set_input_x1({x})
                         .set_input_x2({y});
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def convolution_backward(name, grad_output, input, weight, bias_size,
                             stride, padding, dilation, transposed, output_padding,
                             groups, grad_input_mask):
        assert transposed == 'false'
        assert output_padding == '{0, 0}'

        src_code = ''
        stride = stride.split('{')[-1].split('}')[0].split(', ')
        padding = padding.split('{')[-1].split('}')[0].split(', ')
        dilation = dilation.split('{')[-1].split('}')[0].split(', ')
        grad_input_mask = grad_input_mask.split('{')[-1].split('}')[0].split(', ')
        new_stride = ['1', '1', stride[0], stride[1]]
        new_padding = [padding[0], padding[0], padding[1], padding[1]]
        new_dilation = ['1', '1', dilation[0], dilation[1]]

        stride_str = '{' + ','.join(new_stride) + '}'
        padding_str = '{' + ','.join(new_padding) + '}'
        dilation_str = '{' + ','.join(new_dilation) + '}'

        # XXX(tangzhiyi): assume data format is NCHW
        data_format = 'NCHW'

        # input
        if grad_input_mask[0] == 'True':
            src_code += f"""auto {name}_input_shape = op::Shape("{name}_input_shape")
                              .set_input_x({input});
                            auto {name}_input = op::Conv2DBackpropInput("{name}_input")
                              .set_input_input_size({name}_input_shape)
                              .set_input_filter({weight})
                              .set_input_out_backprop({grad_output})
                              .set_attr_strides({stride_str})
                              .set_attr_pads({padding_str})
                              .set_attr_dilations({dilation_str})
                              .set_attr_groups({groups})
                              .set_attr_data_format("{data_format}");
                            graph.AddOp({name}_input_shape);
                            graph.AddOp({name}_input);"""

        # weight
        if grad_input_mask[1] == 'True':
            src_code += f"""auto {name}_filter_shape = op::Shape("{name}_filter_shape")
                              .set_input_x({weight});
                            auto {name}_filter = op::Conv2DBackpropFilter("{name}_filter")
                              .set_input_x({input})
                              .set_input_filter_size({name}_filter_shape)
                              .set_input_out_backprop({grad_output})
                              .set_attr_strides({stride_str})
                              .set_attr_pads({padding_str})
                              .set_attr_dilations({dilation_str})
                              .set_attr_groups({groups})
                              .set_attr_data_format("NCHW");
                            graph.AddOp({name}_filter_shape);
                            graph.AddOp({name}_filter);"""

        # TODO(tangzhiyi): bias is not supported yet
        assert grad_input_mask[2] == 'False'

        only_input = grad_input_mask[0] == 'True' and grad_input_mask[1] == 'False'
        only_weight = grad_input_mask[0] == 'False' and grad_input_mask[1] == 'True'
        both_input_weight = grad_input_mask[0] == 'True' and grad_input_mask[1] == 'True'

        if only_input:
            src_code += f"""auto {name} = op::IdentityN("{name}")
                              .create_dynamic_input_x(2)
                              .set_dynamic_input_x(0, {name}_input)
                              .set_dynamic_input_x(1, {name}_input)
                              .create_dynamic_output_y(2);
                            graph.AddOp({name});"""
        elif only_weight:
            src_code += f"""auto {name} = op::IdentityN("{name}")
                              .create_dynamic_input_x(2)
                              .set_dynamic_input_x(0, {name}_filter)
                              .set_dynamic_input_x(1, {name}_filter)
                              .create_dynamic_output_y(2);
                            graph.AddOp({name});"""
        elif both_input_weight:
            src_code += f"""auto {name} = op::IdentityN("{name}")
                              .create_dynamic_input_x(2)
                              .set_dynamic_input_x(0, {name}_input)
                              .set_dynamic_input_x(1, {name}_filter)
                              .create_dynamic_output_y(2);
                            graph.AddOp({name});"""
        else:
            raise RuntimeError('not supported!')

        return src_code

    @staticmethod
    def max_pool2d_with_indices_backward(name, grad_output, x, kernel_size,
                                         stride, padding, dilation,ceil_mode,
                                         indices):
        assert len(kernel_size.split(',')) == 2 or len(kernel_size.split(',')) == 1
        assert len(stride.split(',')) == 2 or len(stride.split(',')) == 1
        assert len(padding.split(',')) == 2 or len(padding.split(',')) == 1
        assert len(dilation.split(',')) == 2 or len(dilation.split(',')) == 1

        kernel_size = kernel_size.split('{')[-1].split('}')[0].split(', ')
        stride = stride.split('{')[-1].split('}')[0].split(', ')
        padding = padding.split('{')[-1].split('}')[0].split(', ')
        dilation = dilation.split('{')[-1].split('}')[0].split(', ')

        new_kernel_size = ['1', '1', kernel_size[0], kernel_size[1]]
        new_stride = ['1', '1', stride[0], stride[1]]
        new_padding = ['1', padding[0], padding[1], '1']

        kernel_size_str = '{' + ','.join(new_kernel_size) + '}'
        stride_str = '{' + ','.join(new_stride) + '}'
        padding_str = '{' + ','.join(new_padding) + '}'

        assert dilation == ['1', '1']

        if padding != ['0', '0']:
            padding0 = padding[0]
            padding1 = padding[1]
            padding_str = f'0, 0, 0, 0, {padding0}, {padding0}, {padding1}, {padding1}'
            src_code = f"""TensorDesc {name}_pad_desc(ge::Shape({{4, 2}}), FORMAT_NCHW, DT_INT32);
                           std::vector<int> {name}_pad_value {{ {padding_str} }};
                           Tensor {name}_pad_tensor({name}_pad_desc);
                           setTensorData({name}_pad_tensor, reinterpret_cast<uint8_t*>({name}_pad_value.data()), sizeof(int) * 8, "{name} pad");

                           auto {name}_paddings = op::Const("{name}_paddings")
                             .set_attr_value({name}_pad_tensor);
                           graph.AddOp({name}_paddings);
                           auto {name}_pad = op::PadV3("{name}_pad")
                             .set_input_x({x})
                             .set_input_paddings({name}_paddings);
                           graph.AddOp({name}_pad);
                           auto {name}_fwd_out = op::MaxPool("{name}_fwd_out")
                             .set_input_x({name}_pad)
                             .set_attr_ksize({kernel_size_str})
                             .set_attr_strides({stride_str})
                             .set_attr_padding("VALID")
                             .set_attr_data_format("NCHW");
                           graph.AddOp({name}_fwd_out);
                   
                           auto {name}_bwd = op::MaxPoolGrad("{name}_bwd")
                             .set_input_x1({name}_pad)
                             .set_input_x2({name}_fwd_out)
                             .set_input_grad({grad_output})
                             .set_attr_ksize({kernel_size_str})
                             .set_attr_strides({stride_str})
                             .set_attr_padding("VALID")
                             .set_attr_data_format("NCHW");
                           graph.AddOp({name}_bwd);
                           auto {name} = op::PadV3Grad("{name}")
                             .set_input_x({name}_bwd)
                             .set_input_paddings({name}_paddings);
                           graph.AddOp({name});"""
        else:
            src_code = f"""auto {name}_fwd_out = op::MaxPool("{name}_fwd_out")
                             .set_input_x({x})
                             .set_attr_ksize({kernel_size_str})
                             .set_attr_strides({stride_str})
                             .set_attr_padding("VALID")
                             .set_attr_data_format("NCHW");
                           graph.AddOp({name}_fwd_out);
                           auto {name} = op::MaxPoolGrad("{name}")
                             .set_input_x1({x})
                             .set_input_x2({name}_fwd_out)
                             .set_input_grad({grad_output})
                             .set_attr_ksize({kernel_size_str})
                             .set_attr_strides({stride_str})
                             .set_attr_padding("VALID")
                             .set_attr_data_format("NCHW");
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def where(name, cond, x1, x2, node):
        # TODO(tangzhiyi): need to process scalars
        (cond_node, x1_node, x2_node) = node.args
        assert isinstance(x1_node, torch.fx.node.Node)
        assert isinstance(x2_node, torch.fx.node.Node)

        src_code = f"""// 1. broadcast
                       auto {name}_shape = op::Shape("{name}_cond_shape")
                         .set_input_x({cond});
                       auto {name}_x1_bcast = op::BroadcastTo("{name}_x1_bcast")
                         .set_input_x({x1})
                         .set_input_shape({name}_shape);
                       auto {name}_x2_bcast = op::BroadcastTo("{name}_x2_bcast")
                         .set_input_x({x2})
                         .set_input_shape({name}_shape);
                       auto {name} = op::Select("{name}")
                         .set_input_condition({cond})
                         .set_input_x1({name}_x1_bcast)
                         .set_input_x2({name}_x2_bcast);
                       graph.AddOp({name}_shape);
                       graph.AddOp({name}_x1_bcast);
                       graph.AddOp({name}_x2_bcast);
                       graph.AddOp({name});"""

        return src_code

    @staticmethod
    def le(name, x1, x2, node):
        (x1_node, x2_node) = node.args
        if isinstance(x2_node, torch.fx.node.Node):
            src_code = f"""auto {name} = op::LessEqual("{name}")
                             .set_input_x1({x1})
                             .set_input_x2({x2});
                           graph.AddOp({name});"""
        else:
            # TODO(tangzhiyi): get value type, now assume float
            src_code = f"""std::vector<int64_t> {name}_x2_dims;
                           TensorDesc {name}_x2_desc(ge::Shape({name}_x2_dims), FORMAT_NCHW, DT_FLOAT);
                           Tensor {name}_x2_tensor({name}_x2_desc);
                           float {name}_x2_value = {x2};
                           setTensorData({name}_x2_tensor, reinterpret_cast<uint8_t*>(&{name}_x2_value), sizeof(float), "{name}_x2");

                           auto {name}_x2 = op::Const("{name}_x2")
                             .set_attr_value({name}_x2_tensor);
                           auto {name} = op::LessEqual("{name}")
                             .set_input_x1({x1})
                             .set_input_x2({name}_x2);
                           graph.AddOp({name}_x2);
                           graph.AddOp({name});"""

        return src_code

    @staticmethod
    def scalar_tensor(name, val, node):
        torch_dtype = node.kwargs['dtype']
        cpp_dtype = get_cpp_dtype(torch_dtype)
        ascend_dtype = get_ascend_dtype(torch_dtype)
        src_code = f"""auto {name}_val_tensor = genTensor(std::vector<int64_t>(), FORMAT_NCHW, {ascend_dtype});
                       {cpp_dtype} {name}_val_value = {val};
                       setTensorData({name}_val_tensor, reinterpret_cast<uint8_t*>(&{name}_val_value), sizeof({cpp_dtype}), "{name}_val");
                       auto {name} = op::Const("{name}")
                         .set_attr_value({name}_val_tensor);
                       graph.AddOp({name});"""

        return src_code


    @staticmethod
    def ret_tuple(name, in1, in2):
        src_code = f"""auto {name} = op::IdentityN("{name}")
                         .create_dynamic_input_x(2)
                         .set_dynamic_input_x(0, {in1})
                         .set_dynamic_input_x(1, {in2})
                         .create_dynamic_output_y(2);
                       graph.AddOp({name});"""

        return src_code
    

    @staticmethod
    def ret_triple(name, in1, in2, in3):
        src_code = f"""auto {name} = op::IdentityN("{name}")
                         .create_dynamic_input_x(3)
                         .set_dynamic_input_x(0, {in1})
                         .set_dynamic_input_x(1, {in2})
                         .set_dynamic_input_x(2, {in3})
                         .create_dynamic_output_y(3);
                       graph.AddOp({name});"""

        return src_code


