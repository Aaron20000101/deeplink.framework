#include <csrc_dipu/runtime/device/deviceapis.h>

namespace dipu {

namespace device {

DIPU_API dipu::devapis::DIPUDeviceProperties* getDevicePropertiesWithCache(int32_t device_index);

}  // namespace device
}  // namespace dipu