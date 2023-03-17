import torch
import torch.nn.functional as F
import torch_dipu

def test_cross_entropy_loss(intput, target, devicestr : str):
    device = torch.device(devicestr)
    input = input.to(device)
    target = target.to(device)
    loss = F.cross_entropy(input, target)
    print(f"loss = {loss}")

    loss.backward()
    print(f"loss.grad = {loss.grad}")


input = torch.randn(3, 5, requires_grad=True)
# target with class indices
target = torch.randint(5, (3,), dtype=torch.int64)
test_cross_entropy_loss(input, target, "dipu")
test_cross_entropy_loss(input, target, "cpu")

# target with class probabilities
target = torch.randn(3, 5).softmax(dim=1)
test_cross_entropy_loss(input, target, "dipu")
test_cross_entropy_loss(input, target, "cpu")