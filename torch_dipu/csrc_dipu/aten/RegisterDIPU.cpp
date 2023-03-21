#include <torch/library.h>
#include <ATen/core/dispatch/Dispatcher.h>
#include <ATen/ops/_reshape_alias_native.h>
#include <ATen/native/CPUFallback.h>
#include "DIPUATenFunctions.h"

#include <diopi/functions.h>

#include <csrc_dipu/runtime/rthelper.h>
#include "util/Log.h"

using dnative = dipu::native::DIPUATenFunctions;

namespace at { 
namespace {
  // dipu native ops
  at::Tensor wrapper_empty_memory_format(at::IntArrayRef size, c10::optional<at::ScalarType> dtype_opt,
        c10::optional<at::Layout> layout_opt,
        c10::optional<at::Device> device_opt, c10::optional<bool> pin_memory_opt,
        c10::optional<at::MemoryFormat> memory_format_opt) {
    return dnative::empty(size, dtype_opt, layout_opt, device_opt, pin_memory_opt, memory_format_opt);
  }

  at::Tensor wrapper_empty_strided(at::IntArrayRef size, at::IntArrayRef stride, c10::optional<at::ScalarType> dtype_opt,
      c10::optional<at::Layout> layout_opt, c10::optional<at::Device> device_opt, c10::optional<bool> pin_memory_opt) {
    return dnative::empty_strided(size, stride, dtype_opt, layout_opt, device_opt, pin_memory_opt);
  } 

  at::Tensor& wrapper_copy_(at::Tensor& self, const at::Tensor& src, bool non_blocking) {
    return dnative::copy_(self, src, non_blocking);
  }

  at::Tensor wrapper_DIPU___reshape_alias(const at::Tensor & self, c10::SymIntArrayRef size, c10::SymIntArrayRef stride) {
    return at::native::_reshape_alias(self, C10_AS_INTARRAYREF_SLOW(size), C10_AS_INTARRAYREF_SLOW(stride));
  }

  // only used by cpu_fallback.
  at::Tensor wrapper_DIPU___copy_from_and_resize(const at::Tensor & self, const at::Tensor& dst) {
    dst.resize_as_(self).copy_(self);
    return dst;
  }

  const at::Tensor& wrapper_resize_(const at::Tensor& self, at::IntArrayRef size, c10::optional<at::MemoryFormat> memory_format) {
    // add guard for device switch.
    return dnative::resize_(self, size, memory_format);
  }

  at::Tensor wrapper_DIPU__as_strided(const at::Tensor & self, c10::SymIntArrayRef size, c10::SymIntArrayRef stride, c10::optional<c10::SymInt> storage_offset) {
      // No device check
    // DeviceGuard omitted
    return at::native::as_strided_tensorimpl(self, C10_AS_INTARRAYREF_SLOW(size), C10_AS_INTARRAYREF_SLOW(stride), storage_offset.has_value() ? c10::make_optional(storage_offset->expect_int()) : c10::nullopt);
  }

  at::Tensor wrapper_DIPU__view(const at::Tensor & self, c10::SymIntArrayRef size) {
      // No device check
    // DeviceGuard omitted
    return at::native::view(self, C10_AS_INTARRAYREF_SLOW(size));
  }

  at::Tensor & wrapper_DIPU__zero_(at::Tensor & self) {
      // No device check
    // DeviceGuard omitted
    return at::native::zero_(self);
  }

  // diopi ops
  at::Tensor& wrapperTensorAddOut(const at::Tensor & self, const at::Tensor & other, const at::Scalar & alpha, at::Tensor & out) {
      return dnative::add_out(self, other, alpha, out);
  }

  at::Tensor wrapperRelu(const at::Tensor & self) {
      return dnative::relu(self);
  }

  at::Tensor& wrapperReluInp(at::Tensor & self) {
      return dnative::relu_(self);
  }

  ::std::tuple<at::Tensor,at::Tensor,at::Tensor> wrapperNativeBatchNorm(
      const at::Tensor & input, const c10::optional<at::Tensor> & weight,
      const c10::optional<at::Tensor> & bias,
      const c10::optional<at::Tensor> & running_mean,
      const c10::optional<at::Tensor> & running_var,
      bool training, double momentum, double eps) {
    return dnative::native_batch_norm(input, weight,
          bias, running_mean, running_var, training, momentum, eps);
  }

::std::tuple<at::Tensor&, at::Tensor&, at::Tensor&> wrapperNativeBatchNormOut(
    const at::Tensor & input, const c10::optional<at::Tensor> & weight,
    const c10::optional<at::Tensor> & bias,
    const c10::optional<at::Tensor> & running_mean,
    const c10::optional<at::Tensor> & running_var,
    bool training, double momentum, double eps,
    at::Tensor & out, at::Tensor & save_mean, at::Tensor & save_invstd) {
  return dnative::native_batch_norm_out(
      input, weight, bias, running_mean, running_var,
      training, momentum, eps, out, save_mean, save_invstd);
}

  ::std::tuple<at::Tensor,at::Tensor,at::Tensor> wrapperNativeBatchNormBackward(
      const at::Tensor & grad_out, const at::Tensor & input,
      const c10::optional<at::Tensor> & weight,
      const c10::optional<at::Tensor> & running_mean,
      const c10::optional<at::Tensor> & running_var,
      const c10::optional<at::Tensor> & save_mean,
      const c10::optional<at::Tensor> & save_invstd,
      bool train, double eps, ::std::array<bool,3> output_mask) {
    return dnative::native_batch_norm_backward(
          grad_out, input, weight, running_mean, running_var, save_mean,
          save_invstd, train, eps, output_mask);
  }

  at::Tensor wrapperConvolution2d(
      const at::Tensor & input, const at::Tensor & weight, const c10::optional<at::Tensor> & bias,
      at::IntArrayRef stride, at::IntArrayRef padding, at::IntArrayRef dilation, int64_t groups) {
    return dnative::conv2d(input, weight, bias, stride, padding, dilation, groups);
  }

  at::Tensor & wrapperGeneratorOutRandpermOut(int64_t n, c10::optional<at::Generator> generator, at::Tensor & out) {
    return dnative::randperm_out(n, generator, out);
  }

  at::Tensor & wrapperOutRandpermOut(int64_t n, at::Tensor & out) {
    return dnative::randperm_out(n, out);
  }

  at::Tensor & wrapperFromRandomInp(at::Tensor & self, int64_t from, c10::optional<int64_t> to, c10::optional<at::Generator> generator) {
    return dnative::random_(self, from, to, generator);
  }

  at::Tensor & wrapperToRandomInp(at::Tensor & self, int64_t to, c10::optional<at::Generator> generator) {
    return dnative::random_(self, to, generator);
  }

  at::Tensor & wrapperRandomInp(at::Tensor & self, c10::optional<at::Generator> generator) {
    return dnative::random_(self, generator);
  }

  at::Tensor& wrapperfillScalar_(at::Tensor& self, const at::Scalar& value) {
    // No device check
    // DeviceGuard omitted
    return dnative::fillScalar_(self, value);
  }

at::Tensor & wrapper_sum_out_IntList_out(const at::Tensor & self, at::OptionalIntArrayRef dim, bool keepdim, c10::optional<at::ScalarType> dtype, at::Tensor & out) {
  return dnative::sum_out(self, dim, keepdim, dtype, out);
}

at::Tensor & wrapper_mean_out_out(const at::Tensor & self, at::OptionalIntArrayRef dim, bool keepdim, c10::optional<at::ScalarType> dtype, at::Tensor & out) {
  return dnative::mean_out(self, dim, keepdim, dtype, out);
}

at::Tensor & wrapper_addmm_out_out(const at::Tensor & self, const at::Tensor & mat1, const at::Tensor & mat2, const at::Scalar & beta, const at::Scalar & alpha, at::Tensor & out) {
  return dnative::addmm_out(self, mat1, mat2, beta, alpha, out);
}

at::Tensor wrapper__adaptive_avg_pool2d(const at::Tensor & self, c10::SymIntArrayRef output_size) {
  return dnative::_adaptive_avg_pool2d(self, output_size);
}

at::Tensor & wrapper_out_adaptive_avg_pool2d_out(const at::Tensor & self, c10::SymIntArrayRef output_size, at::Tensor & out) {
  return dnative::adaptive_avg_pool2d_out(self, output_size, out);
}

at::Tensor wrapper__adaptive_avg_pool2d_backward(const at::Tensor & grad_output, const at::Tensor & self) {
  return dnative::adaptive_avg_pool2d_backward(grad_output, self);
}

at::Tensor wrapper_linear(const at::Tensor & input, const at::Tensor & weight, const c10::optional<at::Tensor> & bias) {
  return dnative::linear(input, weight, bias);
}

at::Tensor & wrapper_int_out_log_softmax_out(const at::Tensor & self, int64_t dim, c10::optional<at::ScalarType> dtype, at::Tensor & out) {
  return dnative::log_softmax_out(self, dim, dtype, out);
}

at::Tensor & wrapper__log_softmax_backward_data_out_out(const at::Tensor & grad_output, const at::Tensor & output, int64_t dim, at::ScalarType input_dtype, at::Tensor & out) {
  return dnative::_log_softmax_backward_data_out(grad_output, output, dim, input_dtype, out);
}

at::Tensor wrapper_cross_entropy_loss(const at::Tensor & self, const at::Tensor & target, const c10::optional<at::Tensor> & weight, int64_t reduction, c10::SymInt ignore_index, double label_smoothing) {
  return dnative::cross_entropy_loss(self, target, weight, reduction, ignore_index, label_smoothing);
}

at::Tensor & wrapper_nll_loss_out(const at::Tensor & self, const at::Tensor & target, const c10::optional<at::Tensor> & weight, int64_t reduction, c10::SymInt ignore_index, at::Tensor & out) {
  return dnative::nll_loss_out(self, target, weight, reduction, ignore_index, out);
}

at::Tensor & wrapper_nll_loss_backward_out_grad_input(const at::Tensor & grad_output, const at::Tensor & self, const at::Tensor & target, const c10::optional<at::Tensor> & weight, int64_t reduction, int64_t ignore_index, const at::Tensor & total_weight, at::Tensor & grad_input) {
  return dnative::nll_loss_backward_out_grad_input(grad_output, self, target, weight, reduction, ignore_index, total_weight, grad_input);
}

}  // inner anonymous namespace

static void dipu_fallback(const c10::OperatorHandle& op, DispatchKeySet dispatch_keys,
    torch::jit::Stack* stack) {
  const auto name = c10::toString(op.operator_name());
  std::cout << "fallback to cpu, name=" << c10::toString(op.operator_name()) << std::endl;
  at::native::cpu_fallback(op, stack);
}

// Temporarily not implement 'sub-dispatch from box' (from torch box func -> ourself unbox func)
// which described in design doc.
// because: 1. it need many add type trait code. 2. pytorch seems are sorting out infer and other pre/post code.
// so we shouldn't created a new preprocess logic?
//so just do a simple runtime cpu fallback to support diopi func loss
#define DIOPI_ATEN_FUNC(opname, diopiFunc, wapperFunc) do {           \
    if (reinterpret_cast<void*>(diopiFunc) != nullptr) {                \
        m.impl(opname, TORCH_FN(wapperFunc));                           \
    }  else {                                                           \
        m.impl(opname, torch::CppFunction::makeFromBoxedFunction<&dipu_fallback>());  \
    }                                                                   \
} while (false);

TORCH_LIBRARY_IMPL(_, DIPU_DEVICE_TYPE_MACRO, m) {
    m.fallback(torch::CppFunction::makeFromBoxedFunction<&dipu_fallback>());
}

TORCH_LIBRARY_IMPL(aten, DIPU_DEVICE_TYPE_MACRO, m) {
  // always registered
  m.impl("empty.memory_format", TORCH_FN(wrapper_empty_memory_format));
  m.impl("empty_strided", TORCH_FN(wrapper_empty_strided));
  m.impl("copy_",  TORCH_FN(wrapper_copy_));
  m.impl("_reshape_alias", TORCH_FN(wrapper_DIPU___reshape_alias));
  m.impl("_copy_from_and_resize", TORCH_FN(wrapper_DIPU___copy_from_and_resize));
  m.impl("resize_", TORCH_FN(wrapper_resize_));
  m.impl("as_strided", TORCH_FN(wrapper_DIPU__as_strided));
  m.impl("view", TORCH_FN(wrapper_DIPU__view));
  m.impl("zero_", TORCH_FN(wrapper_DIPU__zero_));

  // register fallback if dipu func not exists
  DIOPI_ATEN_FUNC("add.out", diopiAdd, wrapperTensorAddOut);
  DIOPI_ATEN_FUNC("relu", diopiRelu, wrapperRelu);
  DIOPI_ATEN_FUNC("relu_", diopiReluInp, wrapperReluInp);
  DIOPI_ATEN_FUNC("native_batch_norm", diopiBatchNorm, wrapperNativeBatchNorm);
  DIOPI_ATEN_FUNC("native_batch_norm.out", diopiBatchNorm, wrapperNativeBatchNormOut);
  DIOPI_ATEN_FUNC("native_batch_norm_backward", diopiBatchNormBackward, wrapperNativeBatchNormBackward);
  DIOPI_ATEN_FUNC("conv2d", diopiConvolution2d, wrapperConvolution2d);
  DIOPI_ATEN_FUNC("randperm.generator_out", diopiRandperm, wrapperGeneratorOutRandpermOut);
  DIOPI_ATEN_FUNC("randperm.out", diopiRandperm, wrapperOutRandpermOut);
  DIOPI_ATEN_FUNC("random_.from", diopiRandomInp, wrapperFromRandomInp);
  DIOPI_ATEN_FUNC("random_.to", diopiRandomInp, wrapperToRandomInp);
  DIOPI_ATEN_FUNC("random_", diopiRandomInp, wrapperRandomInp);
  DIOPI_ATEN_FUNC("fill_.Scalar", diopiFill, wrapperfillScalar_);
  DIOPI_ATEN_FUNC("sum.IntList_out", diopiSum, wrapper_sum_out_IntList_out);
  DIOPI_ATEN_FUNC("mean.out", diopiMean, wrapper_mean_out_out);
  DIOPI_ATEN_FUNC("addmm.out", diopiAddmm, wrapper_addmm_out_out);
  DIOPI_ATEN_FUNC("_adaptive_avg_pool2d", diopiAdaptiveAvgPool2d, wrapper__adaptive_avg_pool2d);
  DIOPI_ATEN_FUNC("adaptive_avg_pool2d.out", diopiAdaptiveAvgPool2d, wrapper_out_adaptive_avg_pool2d_out);
  DIOPI_ATEN_FUNC("_adaptive_avg_pool2d_backward", diopiAdaptiveAvgPool2dBackward, wrapper__adaptive_avg_pool2d_backward);
  DIOPI_ATEN_FUNC("linear", diopiLinear, wrapper_linear);
  DIOPI_ATEN_FUNC("log_softmax.int_out", diopiLogSoftmax, wrapper_int_out_log_softmax_out);
  DIOPI_ATEN_FUNC("_log_softmax_backward_data.out", diopiLogSoftmaxBackward, wrapper__log_softmax_backward_data_out_out);
  DIOPI_ATEN_FUNC("cross_entropy_loss", diopiCrossEntropyLoss, wrapper_cross_entropy_loss);
  DIOPI_ATEN_FUNC("nll_loss.out", diopiNLLLoss, wrapper_nll_loss_out);
  DIOPI_ATEN_FUNC("nll_loss2d.out", diopiNLLLoss, wrapper_nll_loss_out);
  DIOPI_ATEN_FUNC("nll_loss_backward.grad_input", diopiNLLLossBackward, wrapper_nll_loss_out);
  DIOPI_ATEN_FUNC("nll_loss2d_backward.grad_input", diopiNLLLossBackward, wrapper_nll_loss_backward_out_grad_input);

}

TORCH_LIBRARY_IMPL(aten, DIPU_AUTOGRAD_DEVICE_TYPE_MACRO, m) {
  DIOPI_ATEN_FUNC("conv2d", diopiConvolution2dBackward, wrapperConvolution2d);
  DIOPI_ATEN_FUNC("linear", diopiLinearBackward, wrapper_linear);
}

} //end ns at
