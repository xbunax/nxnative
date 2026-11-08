// The iOS launcher in Objective-C: the same settings screen as upstream's Launcher.swift / LauncherRow.swift / LauncherSettings.swift, for builds that cannot compile Swift
// (the Windows cross-build). It reads the same dm/launcher.json, keeps the same saved choices (launcher.<VAR> strings in UserDefaults), honours the same environment
// (DM_ENV_FILE_KEYS, DM_ENV_LAUNCH_KEYS, DM_SAVED_CHOICES, DM_LAUNCHER) and exports the same entry point (front_ios.m dm_show_launcher). It is a port, line for line where it can be:
// when upstream changes the Swift files, change this one with them (webui/tests/test_launcher_parity.py compares the two and fails until they agree).
#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <objc/message.h>
#import "CloudSaves.h"
#import "DmGameMenu.h"
#include <math.h>
#include <os/proc.h>
#include <stdio.h>
#include <stdlib.h>

// ---- settings (LauncherSettings.swift: Setting) ----
static NSString *str(NSDictionary *s, NSString *key) { id v = s[key]; return [v isKindOfClass:NSString.class] ? v : @""; }
static NSString *optStr(NSDictionary *s, NSString *key) { id v = s[key]; return [v isKindOfClass:NSString.class] ? v : nil; }
static NSNumber *optNum(NSDictionary *s, NSString *key) { id v = s[key]; return [v isKindOfClass:NSNumber.class] ? v : nil; }
static NSString *sectionTitle(NSDictionary *s) { return optStr(s, @"section") ?: @"Game"; }
static NSString *onValue(NSDictionary *s) { return optStr(s, @"on") ?: @"1"; }
static NSString *offValue(NSDictionary *s) { return optStr(s, @"off") ?: @"0"; }
static BOOL parseDouble(NSString *v, double *out) {   // Swift's Double(String): the whole string is a number
    if (!v.length) return NO;
    const char *c = v.UTF8String; char *end = NULL;
    double d = strtod(c, &end);
    if (end == c || *end) return NO;
    *out = d; return YES;
}
static BOOL isDefault(NSDictionary *s, NSString *v) {   // a range compares as numbers (a slider writes 1.00 for 1.0)
    if ([str(s, @"kind") isEqualToString:@"range"]) {
        double a = NAN, b = NAN; parseDouble(v, &a); parseDouble(str(s, @"default"), &b);
        return fabs(a - b) < 1e-6;
    }
    return [v isEqualToString:str(s, @"default")];
}
static BOOL accepts(NSDictionary *s, NSString *v) {   // a saved choice the game still offers
    NSString *kind = str(s, @"kind");
    if ([kind isEqualToString:@"choice"]) {
        for (NSArray *o in s[@"options"]) if ([o isKindOfClass:NSArray.class] && o.count && [o[0] isEqualToString:v]) return YES;
        return NO;
    }
    if ([kind isEqualToString:@"range"]) {
        if ([v rangeOfString:@"x"].location != NSNotFound || [v rangeOfString:@"X"].location != NSNotFound) return NO;   // no hex: launcher.c's check agrees
        double n; NSNumber *lo = optNum(s, @"min"), *hi = optNum(s, @"max");
        if (!parseDouble(v, &n) || !isfinite(n) || !lo || !hi) return NO;
        return n >= lo.doubleValue && n <= hi.doubleValue;
    }
    if ([kind isEqualToString:@"toggle"]) return [v isEqualToString:onValue(s)] || [v isEqualToString:offValue(s)];
    return YES;
}
static NSSet<NSString *> *keyList(const char *name) {   // a space-separated list of names, empty ones dropped
    NSMutableSet *set = [NSMutableSet set];
    const char *e = getenv(name);
    for (NSString *k in [(e ? [NSString stringWithUTF8String:e] : @"") componentsSeparatedByString:@" "]) if (k.length) [set addObject:k];
    return set;
}

// ---- model (LauncherSettings.swift: LauncherModel) ----
@interface DmLauncherModel : NSObject
@property(readonly) NSArray<NSDictionary *> *settings;
@property(readonly) NSSet<NSString *> *fixed;        // set by an env file or by the launch environment: shown, not changed
@property(readonly) NSSet<NSString *> *fromLaunch;   // of those, the ones the launch environment set
@property(readonly) BOOL ignoreSaved;                // DM_SAVED_CHOICES=0: start from the defaults, and leave the saved choices as they are
@property(readonly) NSMutableDictionary<NSString *, NSString *> *values;
@property(readonly) NSUserDefaults *defaults;
@property(nonatomic, copy) NSString *uiLanguage;
@property(readonly) NSDictionary<NSString *, NSString *> *uiTranslations;
- (instancetype)initWithSettings:(NSArray<NSDictionary *> *)settings translations:(NSDictionary *)translations;
- (NSString *)text:(NSString *)english;
- (void)choose:(NSDictionary *)setting value:(NSString *)value;
@end

@implementation DmLauncherModel
- (instancetype)initWithSettings:(NSArray<NSDictionary *> *)settings translations:(NSDictionary *)translations {
    if (!(self = [super init])) return nil;
    _defaults = NSUserDefaults.standardUserDefaults;
    _uiTranslations = [translations isKindOfClass:NSDictionary.class] ? translations : @{};
    NSString *savedUI = [_defaults stringForKey:@"launcher.uiLanguage"];
    _uiLanguage = [@[@"en", @"zh-Hans"] containsObject:savedUI ?: @""] ? savedUI :
        ([NSLocale.preferredLanguages.firstObject hasPrefix:@"zh"] ? @"zh-Hans" : @"en");
    _settings = settings;
    _fromLaunch = keyList("DM_ENV_LAUNCH_KEYS");
    NSMutableSet *fixed = [_fromLaunch mutableCopy]; [fixed unionSet:keyList("DM_ENV_FILE_KEYS")]; _fixed = fixed;
    const char *saved = getenv("DM_SAVED_CHOICES");
    _ignoreSaved = saved && !strcmp(saved, "0");
    if (_ignoreSaved) fputs("launcher: saved choices ignored (DM_SAVED_CHOICES=0)\n", stderr);
    _values = [NSMutableDictionary dictionary];
    for (NSDictionary *s in settings) {
        NSString *env = str(s, @"env");
        const char *e = getenv(env.UTF8String);
        if ([_fixed containsObject:env] && e) { _values[env] = [NSString stringWithUTF8String:e]; continue; }
        id saved = _ignoreSaved ? nil : [_defaults objectForKey:[@"launcher." stringByAppendingString:env]];   // a string, as launcher.c reads it: not stringForKey:, which turns a number into one
        NSString *sv = [saved isKindOfClass:NSString.class] ? saved : nil;
        _values[env] = (sv && accepts(s, sv)) ? sv : str(s, @"default");   // a saved choice the game no longer offers: its default
    }
    return self;
}
- (void)setUiLanguage:(NSString *)language {
    _uiLanguage = [language copy];
    [_defaults setObject:_uiLanguage forKey:@"launcher.uiLanguage"];
}
- (NSString *)text:(NSString *)english {
    NSString *translated = _uiTranslations[english];
    return [_uiLanguage isEqualToString:@"zh-Hans"] && [translated isKindOfClass:NSString.class] ? translated : english;
}
- (NSString *)valueOf:(NSDictionary *)s { return _values[str(s, @"env")] ?: str(s, @"default"); }
- (NSArray<NSString *> *)sections {
    NSMutableArray *out = [NSMutableArray array];
    for (NSDictionary *s in _settings) if (![out containsObject:sectionTitle(s)]) [out addObject:sectionTitle(s)];
    return out;
}
// A row with "needs" is a sub-setting of the row it names: drawn only while that setting has that value, so a setting that cannot do anything is not offered. A row naming a setting this game does not have stays drawn
- (BOOL)visible:(NSDictionary *)s {
    NSString *n = optStr(s, @"needs");
    NSRange eq = n ? [n rangeOfString:@"="] : NSMakeRange(NSNotFound, 0);
    if (!n || eq.location == NSNotFound) return YES;
    NSString *v = _values[[n substringToIndex:eq.location]];
    return !v || [v isEqualToString:[n substringFromIndex:eq.location + 1]];
}
- (NSArray<NSDictionary *> *)rowsInSection:(NSString *)section {
    NSMutableArray *out = [NSMutableArray array];
    for (NSDictionary *s in _settings) if ([sectionTitle(s) isEqualToString:section] && [self visible:s]) [out addObject:s];
    return out;
}
// A range's label: its percentage, with the size in pixels for the chosen console mode when the list has the base size (the render scale)
- (NSString *)rangeLabel:(NSDictionary *)s value:(double)v {
    NSString *p = [NSString stringWithFormat:@"%ld %%", (long)llround(v * 100)];
    NSDictionary *base = [s[@"base"] isKindOfClass:NSDictionary.class] ? s[@"base"] : nil;
    if (!base) return p;
    NSArray *size = [(_values[@"DM_OPMODE"] ?: @"1") isEqualToString:@"0"] ? base[@"handheld"] : base[@"docked"];
    if (![size isKindOfClass:NSArray.class] || size.count != 2) return p;
    return [NSString stringWithFormat:@"%ld × %ld (%@)", (long)llround([size[0] doubleValue] * v), (long)llround([size[1] doubleValue] * v), p];
}
- (BOOL)changed {
    for (NSDictionary *s in _settings) if (![_fixed containsObject:str(s, @"env")] && !isDefault(s, [self valueOf:s])) return YES;
    return NO;
}
// Reset every launcher choice to the game's defaults on the screen; values fixed by an env file or at launch stay. The saved choices are forgotten when Play applies the defaults (apply keeps no default)
- (void)reset {
    for (NSDictionary *s in _settings) if (![_fixed containsObject:str(s, @"env")]) _values[str(s, @"env")] = str(s, @"default");
    fputs("launcher: settings reset to the game's defaults\n", stderr);
}
// Before the game starts: every setting not set by an env file goes into the environment. Only a choice that differs from the game's default is stored
- (void)apply {
    for (NSDictionary *s in _settings) {
        NSString *env = str(s, @"env"), *v = [self valueOf:s];
        if ([_fixed containsObject:env]) { fprintf(stderr, "launcher: %s kept at %s (%s)\n", env.UTF8String, v.UTF8String, [_fromLaunch containsObject:env] ? "launch environment" : "env file"); continue; }
        if (!_ignoreSaved) { NSString *key = [@"launcher." stringByAppendingString:env]; if (isDefault(s, v)) [_defaults removeObjectForKey:key]; else [_defaults setObject:v forKey:key]; }
        setenv(env.UTF8String, v.UTF8String, 1); fprintf(stderr, "launcher: %s=%s%s\n", env.UTF8String, v.UTF8String, isDefault(s, v) ? "" : " (changed)");
    }
}
// DM_LAUNCHER=0: no screen, but the saved choices still apply (only DM_SAVED_CHOICES=0 ignores them); nothing is written
- (void)choose:(NSDictionary *)s value:(NSString *)v {
    NSString *env = str(s, @"env");
    if ([_fixed containsObject:env] || !accepts(s, v)) return;
    _values[env] = v;
    if (!_ignoreSaved) {
        NSString *key = [@"launcher." stringByAppendingString:env];
        if (isDefault(s, v)) [_defaults removeObjectForKey:key]; else [_defaults setObject:v forKey:key];
    }
    setenv(env.UTF8String, v.UTF8String, 1);
    fprintf(stderr, "launcher: %s=%s (in-game menu)\n", env.UTF8String, v.UTF8String);
}
- (void)applySaved {
    for (NSDictionary *s in _settings) {
        NSString *env = str(s, @"env"), *v = [self valueOf:s];
        if ([_fixed containsObject:env]) continue;
        if (!isDefault(s, v)) { setenv(env.UTF8String, v.UTF8String, 1); fprintf(stderr, "launcher: %s=%s (saved choice)\n", env.UTF8String, v.UTF8String); }
    }
}
@end

// GameMenu.swift: keep the settings-screen model for the live menu, even with DM_LAUNCHER=0.
static DmLauncherModel *gameMenuModel;
static UIMenuElement *gameMenuRow(DmLauncherModel *m, NSDictionary *s) {
    NSString *env = str(s, @"env"), *now = [m valueOf:s];
    BOOL fixed = [m.fixed containsObject:env];
    void (^pick)(NSString *) = ^(NSString *value) {
        [m choose:s value:value]; dm_setting_live(env.UTF8String, value.UTF8String);
    };
    if ([str(s, @"kind") isEqualToString:@"toggle"]) {
        UIAction *action = [UIAction actionWithTitle:[m text:str(s, @"label")] image:nil identifier:nil handler:^(UIAction *a) {
            pick([now isEqualToString:onValue(s)] ? offValue(s) : onValue(s));
        }];
        action.state = [now isEqualToString:onValue(s)] ? UIMenuElementStateOn : UIMenuElementStateOff;
        action.attributes = fixed ? UIMenuElementAttributesDisabled : 0;
        if (fixed) action.subtitle = [m text:@"Set in env.txt"];
        return action;
    }
    NSMutableArray *actions = [NSMutableArray array];
    NSString *current = now;
    for (NSArray *option in s[@"options"] ?: @[]) {
        UIAction *action = [UIAction actionWithTitle:[m text:option[1]] image:nil identifier:nil handler:^(UIAction *a) { pick(option[0]); }];
        action.attributes = fixed ? UIMenuElementAttributesDisabled : 0;
        action.state = [option[0] isEqualToString:now] ? UIMenuElementStateOn : UIMenuElementStateOff;
        if (action.state == UIMenuElementStateOn) current = [m text:option[1]];
        [actions addObject:action];
    }
    NSString *subtitle = fixed ? [NSString stringWithFormat:@"%@, %@", current, [m text:@"set in env.txt"]] : nil;
    UIMenu *menu = [UIMenu menuWithTitle:[m text:str(s, @"label")] image:nil identifier:nil options:UIMenuOptionsSingleSelection children:actions];
    menu.subtitle = subtitle;
    return menu;
}
static NSArray<UIMenuElement *> *gameMenuItems(void) {
    NSArray *names = @[@"2D", @"3D", @"Tap"];
    NSMutableArray *layouts = [NSMutableArray array];
    for (int layout = 0; layout < 3; layout++) if (dm_pad_layout_offered(layout)) {
        UIAction *action = [UIAction actionWithTitle:names[layout] image:nil identifier:nil handler:^(UIAction *a) { dm_pad_layout_set(layout); }];
        action.state = dm_pad_layout() == layout ? UIMenuElementStateOn : UIMenuElementStateOff;
        [layouts addObject:action];
    }
    UIMenu *layout = [UIMenu menuWithTitle:gameMenuModel ? [gameMenuModel text:@"Controller layout"] : @"Controller layout" image:nil identifier:nil options:UIMenuOptionsSingleSelection children:layouts];
    NSMutableArray *items = [NSMutableArray array];
    BOOL placed = NO;
    for (NSString *section in gameMenuModel.sections) {
        NSMutableArray *rows = [NSMutableArray array];
        if ([section isEqualToString:@"Controls"]) { [rows addObject:layout]; placed = YES; }
        for (NSDictionary *s in [gameMenuModel rowsInSection:section]) {
            NSString *kind = str(s, @"kind");
            if (([kind isEqualToString:@"choice"] || [kind isEqualToString:@"toggle"]) && dm_setting_live(str(s, @"env").UTF8String, NULL)) [rows addObject:gameMenuRow(gameMenuModel, s)];
        }
        if (rows.count) [items addObject:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:rows]];
    }
    if (!placed) [items insertObject:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:@[layout]] atIndex:0];
    return items;
}
void *dm_game_menu(void) {
    NSString *title = gameMenuModel ? [gameMenuModel text:@"More settings on the start screen"] : @"";
    UIDeferredMenuElement *deferred = [UIDeferredMenuElement elementWithUncachedProvider:^(void (^done)(NSArray<UIMenuElement *> *)) { done(gameMenuItems()); }];
    return (void *)CFBridgingRetain([UIMenu menuWithTitle:title children:@[deferred]]);
}

// ---- screen (Launcher.swift: LauncherView, LauncherRow.swift: SettingRow) ----
static UIImage *appIcon(void) {
    UIImage *i = [UIImage imageNamed:@"AppIcon"];
    if (i) return i;
    NSDictionary *icons = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleIcons"];
    NSDictionary *primary = [icons isKindOfClass:NSDictionary.class] ? icons[@"CFBundlePrimaryIcon"] : nil;
    NSArray *files = [primary isKindOfClass:NSDictionary.class] ? primary[@"CFBundleIconFiles"] : nil;
    return [files isKindOfClass:NSArray.class] && files.count ? [UIImage imageNamed:files.lastObject] : nil;
}
static NSString *info(NSString *key) { id v = [NSBundle.mainBundle objectForInfoDictionaryKey:key]; return [v isKindOfClass:NSString.class] ? v : nil; }

@interface DmLauncherController : UIViewController <UITableViewDataSource, UITableViewDelegate, UIDocumentPickerDelegate>
- (instancetype)initWithModel:(DmLauncherModel *)model play:(void (^)(void))play;
@end

@implementation DmLauncherController {
    DmLauncherModel *_m;
    void (^_play)(void);
    UITableView *_table;
    NSArray<NSString *> *_sections;   // the sections that have a visible row, then the reset and memory sections
    NSTimer *_timer;
    UILabel *_memory;
    UILabel *_titleLabel, *_versionLabel, *_languageLabel;
    UIButton *_playControl, *_languageControl;
    NSString *_cloudFolder, *_cloudNote;
}
- (instancetype)initWithModel:(DmLauncherModel *)model play:(void (^)(void))play {
    if (!(self = [super init])) return nil;
    _m = model; _play = [play copy];
    self.modalPresentationStyle = UIModalPresentationFullScreen;
    self.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;   // preferredColorScheme(.dark)
    return self;
}
- (void)dealloc { [_timer invalidate]; }
- (UILabel *)labelWithText:(NSString *)text style:(UIFontTextStyle)style secondary:(BOOL)secondary {
    UILabel *l = [UILabel new]; l.text = text; l.numberOfLines = 0;
    l.font = [UIFont preferredFontForTextStyle:style]; l.adjustsFontForContentSizeCategory = YES;
    l.textColor = secondary ? UIColor.secondaryLabelColor : UIColor.labelColor;
    return l;
}
- (UIButton *)playButton {
    UIButtonConfiguration *c = nil;
    SEL glass = NSSelectorFromString(@"prominentGlassButtonConfiguration");   // iOS 26 (.glassProminent); the SDK may predate it
    if ([UIButtonConfiguration respondsToSelector:glass]) c = ((UIButtonConfiguration * (*)(id, SEL)) objc_msgSend)(UIButtonConfiguration.class, glass);
    if (!c) c = [UIButtonConfiguration filledButtonConfiguration];   // .borderedProminent
    c.title = [_m text:@"Play"]; c.buttonSize = UIButtonConfigurationSizeLarge;
    c.titleTextAttributesTransformer = ^NSDictionary *(NSDictionary *a) {
        NSMutableDictionary *d = [a mutableCopy];
        d[NSFontAttributeName] = [UIFont systemFontOfSize:[UIFont preferredFontForTextStyle:UIFontTextStyleTitle3].pointSize weight:UIFontWeightSemibold];   // .title3.weight(.semibold)
        return d;
    };
    UIButton *b = [UIButton buttonWithConfiguration:c primaryAction:[UIAction actionWithHandler:^(UIAction *a) { if (self->_play) self->_play(); }]];
    [b.widthAnchor constraintLessThanOrEqualToConstant:220].active = YES;
    return b;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    UIStackView *left = [UIStackView new]; left.axis = UILayoutConstraintAxisVertical; left.alignment = UIStackViewAlignmentCenter; left.spacing = 12;
    UIImage *icon = appIcon();
    if (icon) {
        UIImageView *v = [[UIImageView alloc] initWithImage:icon];
        v.layer.cornerRadius = 22; v.clipsToBounds = YES; v.isAccessibilityElement = NO;
        [v.widthAnchor constraintEqualToConstant:80].active = YES; [v.heightAnchor constraintEqualToConstant:80].active = YES;
        [left addArrangedSubview:v];
    }
    UILabel *title = [self labelWithText:info(@"CFBundleDisplayName") ?: @"Game" style:UIFontTextStyleTitle1 secondary:NO];
    title.font = [UIFont systemFontOfSize:title.font.pointSize weight:UIFontWeightBold]; title.textAlignment = NSTextAlignmentCenter;
    [left addArrangedSubview:title];
    _titleLabel = title;
    _versionLabel = [self labelWithText:@"" style:UIFontTextStyleCallout secondary:YES];
    [left addArrangedSubview:_versionLabel];
    _playControl = [self playButton]; [left addArrangedSubview:_playControl];
    _languageLabel = [self labelWithText:@"" style:UIFontTextStyleCaption1 secondary:YES];
    _languageControl = [UIButton buttonWithType:UIButtonTypeSystem];
    _languageControl.showsMenuAsPrimaryAction = YES;
    UIStackView *language = [[UIStackView alloc] initWithArrangedSubviews:@[_languageLabel, _languageControl]];
    language.axis = UILayoutConstraintAxisVertical; language.alignment = UIStackViewAlignmentCenter;
    [left addArrangedSubview:language];
    left.translatesAutoresizingMaskIntoConstraints = NO;
    UIView *panel = [UIView new]; panel.translatesAutoresizingMaskIntoConstraints = NO; [panel addSubview:left];
    _table = [[UITableView alloc] initWithFrame:CGRectZero style:UITableViewStyleInsetGrouped];
    _table.dataSource = self; _table.delegate = self; _table.translatesAutoresizingMaskIntoConstraints = NO; _table.allowsSelection = NO;
    [self.view addSubview:panel]; [self.view addSubview:_table];
    UILayoutGuide *g = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [panel.leadingAnchor constraintEqualToAnchor:g.leadingAnchor], [panel.topAnchor constraintEqualToAnchor:g.topAnchor], [panel.bottomAnchor constraintEqualToAnchor:g.bottomAnchor],
        [panel.widthAnchor constraintEqualToAnchor:g.widthAnchor multiplier:1.0 / 3],   // the left third
        [left.centerYAnchor constraintEqualToAnchor:panel.centerYAnchor], [left.leadingAnchor constraintEqualToAnchor:panel.leadingAnchor constant:16], [left.trailingAnchor constraintEqualToAnchor:panel.trailingAnchor constant:-16],
        [_table.leadingAnchor constraintEqualToAnchor:panel.trailingAnchor], [_table.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor],
        [_table.topAnchor constraintEqualToAnchor:self.view.topAnchor], [_table.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor]]];
    [self reload];
    _timer = [NSTimer scheduledTimerWithTimeInterval:2 repeats:YES block:^(NSTimer *t) { [self updateMemory]; }];   // the memory line follows every 2 seconds
}
- (void)reload {
    _titleLabel.text = info(@"CFBundleDisplayName") ?: [_m text:@"Game"];
    _versionLabel.text = [NSString stringWithFormat:@"%@ %@", [_m text:@"Version"], info(@"CFBundleShortVersionString") ?: @""];
    UIButtonConfiguration *playConfig = _playControl.configuration; playConfig.title = [_m text:@"Play"]; _playControl.configuration = playConfig;
    _languageLabel.text = [_m text:@"Interface language"];
    _languageControl.accessibilityLabel = _languageLabel.text;
    NSMutableArray *languages = [NSMutableArray array];
    __weak DmLauncherController *weakSelf = self;
    for (NSArray *item in @[@[@"en", @"English"], @[@"zh-Hans", @"\u7B80\u4F53\u4E2D\u6587"]]) {
        UIAction *action = [UIAction actionWithTitle:item[1] image:nil identifier:nil handler:^(UIAction *a) {
            DmLauncherController *controller = weakSelf;
            if (!controller) return;
            controller->_m.uiLanguage = item[0]; [controller reload];
        }];
        action.state = [_m.uiLanguage isEqualToString:item[0]] ? UIMenuElementStateOn : UIMenuElementStateOff;
        if (action.state == UIMenuElementStateOn) [_languageControl setTitle:item[1] forState:UIControlStateNormal];
        [languages addObject:action];
    }
    _languageControl.menu = [UIMenu menuWithChildren:languages];
    NSMutableArray *s = [NSMutableArray array];
    for (NSString *section in _m.sections) if ([_m rowsInSection:section].count) [s addObject:section];
    _sections = s;
    [_table reloadData];
}
- (NSString *)memoryText { return [NSByteCountFormatter stringFromByteCount:(long long)os_proc_available_memory() countStyle:NSByteCountFormatterCountStyleMemory]; }
- (void)updateMemory { _memory.text = [self memoryText]; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskAll; }
- (NSInteger)numberOfSectionsInTableView:(UITableView *)t { return _sections.count + 3; }
- (NSInteger)tableView:(UITableView *)t numberOfRowsInSection:(NSInteger)n {
    if (n < (NSInteger)_sections.count) return [_m rowsInSection:_sections[n]].count;
    if (n == (NSInteger)_sections.count + 1) {
        BOOL stale = NO;
        _cloudFolder = dm_cloud_saves_path(&stale) ?: @"";
        if (stale && !_cloudFolder.length) _cloudNote = @"The folder you chose before is no longer readable (the app was signed differently). Please choose it again.";
        return _cloudFolder.length ? 3 : 2;
    }
    return 1;
}
- (NSString *)tableView:(UITableView *)t titleForHeaderInSection:(NSInteger)n { return n < (NSInteger)_sections.count ? [_m text:_sections[n]] : nil; }
- (NSString *)tableView:(UITableView *)t titleForFooterInSection:(NSInteger)n {
    if (n == (NSInteger)_sections.count) return [_m text:@"Brings back all settings this game was tested with."];
    if (n == (NSInteger)_sections.count + 1) return [_m text:_cloudNote.length ? _cloudNote : @"Choose a folder in iCloud Drive, and the same one in the Mac app's Cloud saves. The save comes in when the game starts and goes out after each save; a save that is replaced is kept in save-backups."];
    return nil;
}
- (void)chooseCloudFolder {
    UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:@[UTTypeFolder] asCopy:NO];
    picker.allowsMultipleSelection = NO; picker.delegate = self;
    [self presentViewController:picker animated:YES completion:nil];
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    if (!urls.firstObject) return;
    _cloudNote = dm_store_cloud_saves(urls.firstObject)
        ? @"Saved. The game uses this folder when you press Play."
        : @"That folder could not be remembered — try a different one.";
    [self reload];
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {}
- (UITableViewCell *)tableView:(UITableView *)t cellForRowAtIndexPath:(NSIndexPath *)p {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:nil];
    if (p.section == (NSInteger)_sections.count) {   // Reset to tested defaults
        UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
        [b setTitle:[_m text:@"Reset to tested defaults"] forState:UIControlStateNormal];
        b.enabled = _m.changed; b.contentHorizontalAlignment = UIControlContentHorizontalAlignmentLeading;
        [b addAction:[UIAction actionWithHandler:^(UIAction *a) { [self->_m reset]; [self reload]; }] forControlEvents:UIControlEventTouchUpInside];
        [self pin:b in:cell]; return cell;
    }
    if (p.section == (NSInteger)_sections.count + 1) {   // Cloud saves (CloudSavesSection)
        if (p.row == 0) {
            cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil];
            cell.textLabel.text = [_m text:@"Cloud saves"];
            cell.detailTextLabel.text = _cloudFolder.length ? _cloudFolder.lastPathComponent : [_m text:@"Off"];
            cell.detailTextLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
        } else {
            UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
            button.contentHorizontalAlignment = UIControlContentHorizontalAlignmentLeading;
            if (p.row == 1) {
                [button setTitle:[_m text:_cloudFolder.length ? @"Choose a different folder…" : @"Choose a folder in iCloud Drive…"] forState:UIControlStateNormal];
                [button addAction:[UIAction actionWithHandler:^(UIAction *a) { [self chooseCloudFolder]; }] forControlEvents:UIControlEventTouchUpInside];
            } else {
                [button setTitle:[_m text:@"Turn off cloud saves"] forState:UIControlStateNormal];
                [button setTitleColor:UIColor.systemRedColor forState:UIControlStateNormal];
                [button addAction:[UIAction actionWithHandler:^(UIAction *a) { dm_clear_cloud_saves(); self->_cloudNote = @""; [self reload]; }] forControlEvents:UIControlEventTouchUpInside];
            }
            [self pin:button in:cell];
        }
        return cell;
    }
    if (p.section == (NSInteger)_sections.count + 2) {   // Memory available
        UILabel *name = [self labelWithText:[_m text:@"Memory available"] style:UIFontTextStyleBody secondary:NO];
        _memory = [self labelWithText:[self memoryText] style:UIFontTextStyleBody secondary:YES];
        _memory.font = [UIFont monospacedDigitSystemFontOfSize:_memory.font.pointSize weight:UIFontWeightRegular];
        UIStackView *row = [[UIStackView alloc] initWithArrangedSubviews:@[name, _memory]]; row.distribution = UIStackViewDistributionEqualSpacing;
        [self pin:row in:cell]; return cell;
    }
    [self fill:cell with:[_m rowsInSection:_sections[p.section]][p.row]];
    return cell;
}
- (void)pin:(UIView *)v in:(UITableViewCell *)cell {
    v.translatesAutoresizingMaskIntoConstraints = NO; [cell.contentView addSubview:v];
    UILayoutGuide *m = cell.contentView.layoutMarginsGuide;
    [NSLayoutConstraint activateConstraints:@[[v.leadingAnchor constraintEqualToAnchor:m.leadingAnchor], [v.trailingAnchor constraintEqualToAnchor:m.trailingAnchor],
                                              [v.topAnchor constraintEqualToAnchor:cell.contentView.topAnchor constant:8], [v.bottomAnchor constraintEqualToAnchor:cell.contentView.bottomAnchor constant:-8]]];
}
// One launcher setting as a row (a menu, a slider with its percentage, a toggle). A row whose setting is fixed by an env file or by the launch environment is shown but disabled
- (void)fill:(UITableViewCell *)cell with:(NSDictionary *)s {
    NSString *env = str(s, @"env"), *kind = str(s, @"kind");
    BOOL locked = [_m.fixed containsObject:env];
    NSString *note = [_m text:str(s, @"note")];
    if (locked) note = [(note.length ? [note stringByAppendingString:@" · "] : @"") stringByAppendingString:[_m text:[_m.fromLaunch containsObject:env] ? @"Set at launch" : @"Set by an env file"]];
    UIStackView *label = [UIStackView new]; label.axis = UILayoutConstraintAxisVertical; label.spacing = 4;
    [label addArrangedSubview:[self labelWithText:[_m text:str(s, @"label")] style:UIFontTextStyleBody secondary:NO]];
    if (note.length) [label addArrangedSubview:[self labelWithText:note style:UIFontTextStyleFootnote secondary:YES]];
    [label setContentHuggingPriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    NSString *value = [_m valueOf:s];
    UIView *row;
    if ([kind isEqualToString:@"choice"]) {
        NSMutableArray *actions = [NSMutableArray array]; NSString *current = value;
        for (NSArray *o in s[@"options"]) {
            if (![o isKindOfClass:NSArray.class] || o.count < 2) continue;
            UIAction *a = [UIAction actionWithTitle:[_m text:o[1]] image:nil identifier:nil handler:^(UIAction *x) { self->_m.values[env] = o[0]; [self reload]; }];
            a.state = [o[0] isEqualToString:value] ? UIMenuElementStateOn : UIMenuElementStateOff;
            if (a.state == UIMenuElementStateOn) current = [_m text:o[1]];
            [actions addObject:a];
        }
        UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
        [b setTitle:current forState:UIControlStateNormal];
        b.menu = [UIMenu menuWithChildren:actions]; b.showsMenuAsPrimaryAction = YES;
        [b setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
        UIStackView *h = [[UIStackView alloc] initWithArrangedSubviews:@[label, b]]; h.alignment = UIStackViewAlignmentCenter; h.spacing = 12;
        row = h;
    } else if ([kind isEqualToString:@"range"]) {
        double lo = optNum(s, @"min") ? optNum(s, @"min").doubleValue : 0, hi = optNum(s, @"max") ? optNum(s, @"max").doubleValue : 1, step = optNum(s, @"step") ? optNum(s, @"step").doubleValue : 0.05;
        double v; if (!parseDouble(value, &v)) v = hi;
        UILabel *pct = [self labelWithText:[_m rangeLabel:s value:v] style:UIFontTextStyleBody secondary:YES];
        pct.font = [UIFont monospacedDigitSystemFontOfSize:pct.font.pointSize weight:UIFontWeightRegular];
        UIStackView *top = [[UIStackView alloc] initWithArrangedSubviews:@[label, pct]]; top.spacing = 12; top.alignment = UIStackViewAlignmentTop;
        [pct setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
        UISlider *sl = [UISlider new]; sl.minimumValue = lo; sl.maximumValue = hi; sl.value = v; sl.accessibilityLabel = [_m text:str(s, @"label")];
        __weak UISlider *weak = sl;
        [sl addAction:[UIAction actionWithHandler:^(UIAction *a) {   // Slider(step:): snap to the step
            double x = weak.value; if (step > 0) x = MIN(hi, MAX(lo, lo + round((x - lo) / step) * step));
            weak.value = (float)x; self->_m.values[env] = [NSString stringWithFormat:@"%.2f", x];
            pct.text = [self->_m rangeLabel:s value:x]; weak.accessibilityValue = pct.text;
        }] forControlEvents:UIControlEventValueChanged];
        [sl addAction:[UIAction actionWithHandler:^(UIAction *a) { [self reload]; }] forControlEvents:UIControlEventTouchUpInside | UIControlEventTouchUpOutside | UIControlEventTouchCancel];
        UIStackView *v2 = [[UIStackView alloc] initWithArrangedSubviews:@[top, sl]]; v2.axis = UILayoutConstraintAxisVertical; v2.spacing = 8;
        row = v2;
    } else {
        UISwitch *sw = [UISwitch new]; sw.on = [value isEqualToString:onValue(s)];
        [sw addAction:[UIAction actionWithHandler:^(UIAction *a) { self->_m.values[env] = ((UISwitch *)a.sender).on ? onValue(s) : offValue(s); [self reload]; }] forControlEvents:UIControlEventValueChanged];
        [sw setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
        UIStackView *h = [[UIStackView alloc] initWithArrangedSubviews:@[label, sw]]; h.alignment = UIStackViewAlignmentCenter; h.spacing = 12;
        row = h;
    }
    [self pin:row in:cell];
    if (locked) { cell.contentView.userInteractionEnabled = NO; cell.contentView.alpha = 0.4; }   // .disabled(locked)
}
@end

// Shows the launcher over the root view controller and calls done once the settings are in the environment; false (done is not called) when there is no launcher
bool dm_show_launcher(void *viewController, void (*done)(void)) {
    const char *dm = getenv("DM_APP_DM");
    NSURL *dir = dm ? [NSURL fileURLWithPath:[NSString stringWithUTF8String:dm]] : [NSBundle.mainBundle.resourceURL URLByAppendingPathComponent:@"dm"];
    NSURL *url = [dir URLByAppendingPathComponent:@"launcher.json"];
    NSData *data = url ? [NSData dataWithContentsOfURL:url] : nil;
    if (!data) return false;
    NSDictionary *file = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    NSArray *list = [file isKindOfClass:NSDictionary.class] ? file[@"settings"] : nil;
    BOOL valid = [list isKindOfClass:NSArray.class] && list.count;
    for (id s in list) {   // the Swift decoder needs these five strings in every setting
        if (!valid) break;
        valid = [s isKindOfClass:NSDictionary.class];
        for (NSString *key in @[@"env", @"kind", @"label", @"note", @"default"]) if (valid && ![s[key] isKindOfClass:NSString.class]) valid = NO;
    }
    if (!valid) { fputs("[RED] launcher: dm/launcher.json cannot be read; starting the game\n", stderr); return false; }
    DmLauncherModel *model = [[DmLauncherModel alloc] initWithSettings:list translations:file[@"uiTranslations"]];
    gameMenuModel = model;
    const char *off = getenv("DM_LAUNCHER");
    if (off && !strcmp(off, "0")) { fputs("launcher: off (DM_LAUNCHER=0)\n", stderr); [model applySaved]; return false; }
    UIViewController *parent = (__bridge UIViewController *)viewController;
    __block DmLauncherController *host = nil;
    host = [[DmLauncherController alloc] initWithModel:model play:^{
        DmLauncherController *h = host;
        if (!h) return;
        host = nil;
        [model apply];
        [h dismissViewControllerAnimated:NO completion:^{ done(); }];
    }];
    [parent presentViewController:host animated:NO completion:nil];
    fprintf(stderr, "launcher: %lu settings shown\n", (unsigned long)list.count);
    return true;
}
