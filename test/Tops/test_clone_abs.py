import torch
import torch.fx

class MyModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.param = torch.nn.Parameter(torch.rand(3, 4))
        self.linear = torch.nn.Linear(4, 5)

    def forward(self, a, b):
        output0 = torch.ops.aten.add(a, b)
        output1 = torch.ops.aten.clone(output0)
        output2 = torch.ops.aten.abs(output1)
        output3 = torch.ops.aten.mul(output1, output2)
        return output3

a = torch.randn(10, 10)
b = torch.randn(10, 10)

enflame_model = MyModule()
compiled_model = torch.compile(enflame_model, backend="topsgraph")
resenflame = compiled_model(a, b)

torch_model = MyModule()
restorch = torch_model(a, b)

compare = torch.allclose(resenflame, restorch, equal_nan=True)

print(f'Tests clone, abs result\n{compare}')
