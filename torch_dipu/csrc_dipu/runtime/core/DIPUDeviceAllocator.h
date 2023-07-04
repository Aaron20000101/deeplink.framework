// Copyright (c) 2023, DeepLink.
#pragma once

#include <c10/core/Allocator.h>
#include <c10/core/Device.h>

#include <csrc_dipu/common.h>
#include <csrc_dipu/runtime/device/deviceapis.h>
#include <csrc_dipu/runtime/core/MemChecker.h>
#include <iostream>

namespace dipu {

#define DIPU_DEBUG_ALLOCATOR(mask, x) \
  {                                   \
    static int value = []() { auto env = std::getenv("DIPU_DEBUG_ALLOCATOR"); return env ? std::atoi(env) : 0; }();    \
    if ((mask & value) == mask)       \
    {                                 \
      std::cout << x << std::endl;    \
    }                                 \
  }

  static void DIPUDeviceAllocatorDeleter(void *ptr);

  class DIPU_API DIPUAllocator : public c10::Allocator
  {
  public:
    DIPUAllocator()
    {
      auto device = devapis::current_device();
      devapis::setDevice(device);
    }

    inline virtual c10::DataPtr allocate(size_t size) const
    {
      auto idx = devapis::current_device();
      return this->allocate(size, idx);
    }
    c10::DeleterFnPtr raw_deleter() const override
    {
      return &DIPUDeviceAllocatorDeleter;
    }

  private:
    static std::mutex mutex_;
    c10::DataPtr allocate(size_t nbytes, c10::DeviceIndex device_index) const
    {
      std::lock_guard<std::mutex> lock(mutex_);
      void *data = nullptr;
      devapis::mallocDevice(&data, nbytes);
      DIPU_DEBUG_ALLOCATOR(1, "devapis::mallocDevice: malloc " << nbytes << " nbytes, ptr:" << data);
      MemChecker::instance().insert(data, nbytes);
      return {data, data, &DIPUDeviceAllocatorDeleter, c10::Device(dipu::DIPU_DEVICE_TYPE, device_index)};
    }
  };

  static void DIPUDeviceAllocatorDeleter(void *ptr) {
    if (ptr)
    {
      MemChecker::instance().erase(ptr);
      DIPU_DEBUG_ALLOCATOR(2, "devapis::freeDevice: free " << ptr);
      devapis::freeDevice(ptr);
      ptr = nullptr;
    }
  }


}  // namespace dipu
