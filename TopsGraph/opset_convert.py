import torch
import torch.fx

import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from common.op_transformer import OpSetTransformer
from TopsGraph.conversion import patterns, conversions

def topsgraph_opset_convert(
    gm: torch.fx.GraphModule,
):
    return OpSetTransformer(patterns, "tops", conversions).transform(gm)