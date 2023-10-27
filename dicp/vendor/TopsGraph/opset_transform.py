import torch
import torch.fx

from dicp.dynamo_bridge.op_transformer import OpSetTransformer
from dicp.vendor.TopsGraph.conversion import AtenToTopsTrasformer
from dicp.vendor.TopsGraph.conversion import patterns, conversions
from dicp.dynamo_bridge.compile_fx import is_torch_210

if is_torch_210:
    from dicp.dynamo_bridge.op_transformer import BackendPatternMatcherTransformer
    from dicp.vendor.TopsGraph.conversion import tops_patterns, tops_patterns_cls_list

def topsgraph_opset_transform(
    gm: torch.fx.GraphModule,
):

    # TODO seperate backendPatterMatch
    if is_torch_210:
        gm = BackendPatternMatcherTransformer(
            tops_patterns, tops_patterns_cls_list).transform(gm)


    gm = OpSetTransformer(patterns).transform(gm)
    gm = AtenToTopsTrasformer(gm).transform()

    if is_torch_210:
        gm = BackendPatternMatcherTransformer(
            tops_patterns, tops_patterns_cls_list).transform(gm)

    return gm
