#ifndef RUNNER_FLUTTER_WINDOW_H_
#define RUNNER_FLUTTER_WINDOW_H_

#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <flutter/method_channel.h>
#include <flutter/encodable_value.h>

#include <memory>

#include "win32_window.h"

// A window that does nothing but host a Flutter view.
class FlutterWindow : public Win32Window {
 public:
  // Creates a new FlutterWindow hosting a Flutter view running |project|.
  explicit FlutterWindow(const flutter::DartProject& project,
                         bool initially_visible = true, bool quick = false);
  virtual ~FlutterWindow();

 protected:
  // Win32Window:
  bool OnCreate() override;
  void OnDestroy() override;
  LRESULT MessageHandler(HWND window, UINT const message, WPARAM const wparam,
                         LPARAM const lparam) noexcept override;

 private:
  // The project to run.
  flutter::DartProject project_;

  // The Flutter instance hosted by this window.
  std::unique_ptr<flutter::FlutterViewController> flutter_controller_;
  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
  std::unique_ptr<FlutterWindow> quick_window_;
  std::unique_ptr<FlutterWindow> editor_window_;
  flutter::EncodableValue api_ready_;
  flutter::EncodableValue editor_launch_;
  bool editor_ready_ = false;
  bool first_frame_shown_ = false;
  int initial_show_ = SW_SHOWNORMAL;
  bool initial_restore_maximized_ = false;
  bool initially_visible_;
  bool quick_;
  static FlutterWindow* root_;
  void Activate();
};

#endif  // RUNNER_FLUTTER_WINDOW_H_
