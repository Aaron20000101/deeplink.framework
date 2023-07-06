// Copyright (c) 2023, DeepLink.

#include "DIPUCachingAllocator.h"
#include "DIPUDeviceAllocator.h"
#include <stdint.h>
#include <map>
#include <set>
#include <unordered_map>
#include <list>
#include <deque>
#include <mutex>

namespace dipu {

static void deleteBSContext(void*);

class BSCachingAllocator: public CacheAllocator {

  mutable std::unordered_map<size_t, std::deque<void*>> idel_blocks_;
  mutable std::set<void*> allocated_;
  mutable std::unordered_map<void*, DIPUEvent> events_;
  mutable size_t idel_blocks_num_ = 0;
  mutable size_t total_blocks_num_ = 0;
  mutable c10::Device device_;
  using mutex_t = std::mutex;
  mutable mutex_t mutex_;

public:
  BSCachingAllocator(c10::Allocator* raw_allocator): CacheAllocator(raw_allocator), device_(c10::DeviceType::CPU) {
  }

  ~BSCachingAllocator() {
    while (!allocated_.empty()) {
      empty_cache();
    }
  }

  size_t getAllocateSize(size_t nbytes) const{
    static constexpr size_t kMinAllocationSize = 512;
    size_t allocateSize = ((nbytes + kMinAllocationSize - 1) / kMinAllocationSize) * kMinAllocationSize;
    return allocateSize;
  }

  c10::DataPtr allocate(size_t size) const override{
    const size_t nbytes = getAllocateSize(size);
    std::lock_guard<mutex_t> lk(mutex_);
    void* ptr = nullptr;
    auto& idel_blocks = idel_blocks_[nbytes];
    int find_count = 0;
    const int max_find_count = idel_blocks.size();
    while ((find_count++) < max_find_count) {
      auto  temp_ptr = idel_blocks.front();
      idel_blocks.pop_front();
      const bool event_exist = events_.count(temp_ptr) > 0;
      if ((!event_exist) || events_[temp_ptr].query()) {
        if (event_exist) {
          events_.erase(temp_ptr);
        }
        ptr = temp_ptr;
        DIPU_DEBUG_ALLOCATOR(4, "BSCachingAllocator: reuse " << size << " bytes, ptr:" << ptr << ",block size:" << nbytes << ",allocator:" << this << ",find_count:" << find_count << "/" << max_find_count << ", event num:" << events_.size() << ",idel_blocks_num_:" << idel_blocks_num_ << ",total_blocks_num_" << total_blocks_num_);
        idel_blocks_num_--;
        if (events_.size() > 64) {
          recycleEvent();
        }
        break;
      } else {
        idel_blocks.push_back(temp_ptr);
      }
    }

    if (ptr == nullptr){
      auto data_ptr = raw_allocator()->allocate(nbytes);
      ptr = data_ptr.get();
      device_ = data_ptr.device();
      data_ptr.release_context();
      allocated_.insert(ptr);
      total_blocks_num_++;
      DIPU_DEBUG_ALLOCATOR(4, "BSCachingAllocator: allocate " << nbytes << ", requires:" << size << " bytes, ptr:" << ptr << ",allocator:" << this);
    }

    c10::DataPtr data_ptr(ptr, makeContext(ptr, size), deleteBSContext, device_);
    return data_ptr;
  }

  void restore(size_t size, void* ptr) const {
    const size_t nbytes = getAllocateSize(size);
    DIPU_DEBUG_ALLOCATOR(8, "BSCachingAllocator: restore " << nbytes << ", used:" << size << " bytes, ptr:" << ptr << ",allocator:" << this);
    std::lock_guard<mutex_t> lk(mutex_);
    events_[ptr].record();
    idel_blocks_[nbytes].push_back(ptr);
    idel_blocks_num_++;
  }

  void recycleEvent() const{
    for (auto iter = events_.begin(); iter != events_.end();) {
      auto key = iter->first;
      auto& event = iter->second;
      iter++;
      if (event.query()) {
        events_.erase(key);
      }
    }
  }

  void empty_cache() {
    std::lock_guard<mutex_t> lk(mutex_);
    for(auto iter = idel_blocks_.begin(); iter != idel_blocks_.end(); ++iter) {
      auto& idel_blocks = iter->second;
      while (!idel_blocks.empty()) {
        auto ptr = idel_blocks.front();
        events_[ptr].synchronize();
        raw_allocator()->raw_deallocate(ptr);
        total_blocks_num_--;
        idel_blocks.pop_front();
        events_.erase(ptr);
        allocated_.erase(ptr);
      }
    }
  }

  struct Context {
    void* ptr_;
    size_t size_;
    const BSCachingAllocator* allocator_;
    Context(void* ptr, size_t size, const BSCachingAllocator* allocator):ptr_(ptr), size_(size), allocator_(allocator) {

    }
    ~Context() {
      allocator_->restore(size_, ptr_);
    }
  };

  void* makeContext(void* ptr, size_t size) const{
    auto* ctx = new Context(ptr, size, this);
    return ctx;
  }

};

static void deleteBSContext(void* ptr) {
  auto ctx = static_cast<BSCachingAllocator::Context*>(ptr);
  delete ctx;
}


DIPU_REGISTER_ALLOCATOR("BS", dipu::DIPU_DEVICE_TYPE, BSCachingAllocator, 0);

} // namespace dipu