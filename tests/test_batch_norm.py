import torch

torch.ops.load_library("../build/libtorch_dipu.so")

input = torch.randn(2, 3, 4).cuda()
t = input.view(3, -1)
m = torch.mean(t, 1)
v = torch.var(t, 1)

result = torch.nn.functional.batch_norm(input, m, v)
print(result)

result = torch.nn.functional.batch_norm(input.cpu(), m.cpu(), v.cpu())
print(result)