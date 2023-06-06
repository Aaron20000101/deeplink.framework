import os
import torch

from torch._inductor.decomposition import decompositions

tops_debug = True if os.getenv('TOPS_DEBUG', default='False') == 'True' else False

aten = torch.ops.aten
decomp_del_keys = [aten._native_batch_norm_legit_functional.default,
                  aten.convolution_backward.default, aten._softmax.default,
                  aten._log_softmax.default, aten.gelu.default,
                  aten.hardswish.default, aten.dot.default]
def get_decomp():
    for del_key in decomp_del_keys:
        if del_key in decompositions:
            del decompositions[del_key]
    return decompositions

decomp = get_decomp()
