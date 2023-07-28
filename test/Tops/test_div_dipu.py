import os
import torch
import torch.fx
os.environ["DIPU_MOCK_CUDA"] = "false"
import torch_dipu


class MyModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.param = torch.nn.Parameter(torch.rand(3, 4))
        self.linear = torch.nn.Linear(4, 5)

    def forward(self, a, b):
        r = torch.ops.aten.div(a, b)
        return r

os.environ['DICP_TOPS_DIPU'] = 'True'
os.environ['DIPU_MOCK_CUDA'] = 'false'
device_id = os.getenv('DICP_TOPS_DEVICE_ID', default='0')
a = torch.arange(16).reshape(4, 4).float()
b = 2

m = MyModule()
compiled_model = torch.compile(m, backend="topsgraph")
r1 = compiled_model(a.to(f"dipu:{device_id}"), b).cpu()

torch._dynamo.reset()

m = MyModule()
r2 = m(a, b).cpu()

print(f'\n****************************\n')

print(f"r1: {r1}")
print(f"r2: {r2}")

print(f"r1 - r2:\n{r1 - r2}")

print(f"nan test: r1-{torch.isnan(r1).any()}, r2-{torch.isnan(r2).any()}" )
print(f'torch.allclose:{torch.allclose(r1, r2)}')
print(f'torch.eq:{torch.eq(r1, r2).all()}')
