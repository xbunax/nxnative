#include <stdbool.h>

// Fallback only: ios_cross_compile.py links this when the stage has no ObjC launcher
// (webui/overlays/dm/ios/Sources/DmLauncher.m), because the Windows cross-build cannot compile
// upstream's Swift launcher. Returning false starts the game at once with its defaults.
bool dm_show_launcher(void *view_controller, void (*done)(void)) {
    (void)view_controller;
    (void)done;
    return false;
}

#import <UIKit/UIKit.h>
#import "DmGameMenu.h"
void *dm_game_menu(void) {
    NSMutableArray *items = [NSMutableArray array];
    NSArray *names = @[@"2D", @"3D", @"Tap"];
    for (int layout = 0; layout < 3; layout++) if (dm_pad_layout_offered(layout)) {
        UIAction *a = [UIAction actionWithTitle:names[layout] image:nil identifier:nil handler:^(UIAction *action) { dm_pad_layout_set(layout); }];
        a.state = dm_pad_layout() == layout ? UIMenuElementStateOn : UIMenuElementStateOff;
        [items addObject:a];
    }
    return (void *)CFBridgingRetain([UIMenu menuWithTitle:@"Controller layout" children:items]);
}
