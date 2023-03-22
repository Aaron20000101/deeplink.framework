import torch
import torch.fx

import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from third_party.DICP.common.op_transformer import OpSetTransformer
from third_party.DICP.TopsGraph.conversion import patterns, conversions

def topsgraph_opset_transform(
    gm: torch.fx.GraphModule,
):
    return OpSetTransformer(patterns, conversions).transform(gm)