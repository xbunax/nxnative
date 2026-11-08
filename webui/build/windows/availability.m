// Windows-hosted clang has no Darwin compiler-rt. Its __builtin_available checks
// call this helper; compare through Foundation rather than assuming the minimum
// deployment target is the device's actual OS (newer Metal APIs are optional).
#import <Foundation/Foundation.h>
#include <stdint.h>

int32_t __isPlatformVersionAtLeast(uint32_t platform, uint32_t major, uint32_t minor, uint32_t patch) {
    if (platform != 2) return 0;   // PLATFORM_IOS: this builder targets iPhoneOS only.
    NSOperatingSystemVersion version = {(NSInteger)major, (NSInteger)minor, (NSInteger)patch};
    return [NSProcessInfo.processInfo isOperatingSystemAtLeastVersion:version];
}
