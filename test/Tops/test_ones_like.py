import random

import torch
import torch._dynamo

class MyModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.param = torch.nn.Parameter(torch.rand(3, 4))
        self.linear = torch.nn.Linear(4, 5)

    def forward(self, a):
        layer0 = torch.ops.aten.add(a, a)
        layer1 = torch.ops.aten.ones_like(layer0)
        layer2 = torch.ops.aten.add(layer0, layer1)
        return layer2

x = random.randint(1, 10)
y = random.randint(1, 10)
a = torch.randn(x, y)

enflame_model = MyModule()
compiled_model = torch.compile(enflame_model, backend="topsgraph")
r1 = compiled_model(a)
 
torch._dynamo.reset()

torch_model = MyModule()
r2 = torch_model(a)

print(f"Test ones_like op result:{torch.allclose(r1, r2, equal_nan=True)}")
