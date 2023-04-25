import torch
import torch.fx
from dicp.TopsGraph.opset_transform import topsgraph_opset_transform

class MyModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.param = torch.nn.Parameter(torch.rand(3, 4))
        self.linear = torch.nn.Linear(4, 5)

    def forward(self, a, b, c):
        t0 = torch.ops.aten.sub(b, c)
        t1 = torch.ops.aten.add(b, c)
        t2 = torch.ops.aten.mul(b, c)
        r1 = torch.ops.aten.addmm(t0, t1, t2)

        return r1

a1 = torch.randn(10, 10)
b1 = torch.randn(10, 10)
c1 = torch.randn(10, 10)

menflame = MyModule()
#compiled_model = torch.compile(menflame, backend="inductor")
print("##########################")
compiled_model = torch.compile(menflame, backend="topsgraph")
resenflame = compiled_model(a1, b1, c1)
print(f'\n*******result*******\n resenflame \n {resenflame}\n*******result*******\n')