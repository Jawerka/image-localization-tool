#include "flutter_window.h"

#include <optional>
#include <flutter/standard_method_codec.h>

#include "flutter/generated_plugin_registrant.h"

FlutterWindow* FlutterWindow::root_ = nullptr;

namespace {
// CF_DIB вставляется как изображение, а не путь к временному файлу.
bool CopyImage(HWND owner, const flutter::EncodableValue* arguments) {
  if (!arguments) return false;
  const auto* map = std::get_if<flutter::EncodableMap>(arguments);
  if (!map) return false;
  auto w = map->find(flutter::EncodableValue("width"));
  auto h = map->find(flutter::EncodableValue("height"));
  auto pixels = map->find(flutter::EncodableValue("rgba"));
  if (w == map->end() || h == map->end() || pixels == map->end()) return false;
  const auto* width = std::get_if<int32_t>(&w->second);
  const auto* height = std::get_if<int32_t>(&h->second);
  const auto* rgba = std::get_if<std::vector<uint8_t>>(&pixels->second);
  if (!width || !height || !rgba || *width <= 0 || *height <= 0) return false;
  const uint64_t size = uint64_t(*width) * uint64_t(*height) * 4;
  if (size > 512 * 1024 * 1024 || size != rgba->size()) return false;
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, sizeof(BITMAPINFOHEADER) + size);
  if (!memory) return false;
  auto* header = static_cast<BITMAPINFOHEADER*>(GlobalLock(memory));
  if (!header) { GlobalFree(memory); return false; }
  *header = {};
  header->biSize = sizeof(BITMAPINFOHEADER);
  header->biWidth = *width;
  header->biHeight = *height;
  header->biPlanes = 1;
  header->biBitCount = 32;
  header->biCompression = BI_RGB;
  header->biSizeImage = static_cast<DWORD>(size);
  auto* destination = reinterpret_cast<uint8_t*>(header + 1);
  for (int y = 0; y < *height; ++y) {
    for (int x = 0; x < *width; ++x) {
      const size_t source = (size_t(y) * *width + x) * 4;
      const size_t target = (size_t(*height - y - 1) * *width + x) * 4;
      destination[target] = (*rgba)[source + 2];
      destination[target + 1] = (*rgba)[source + 1];
      destination[target + 2] = (*rgba)[source];
      destination[target + 3] = 255;
    }
  }
  GlobalUnlock(memory);
  if (!OpenClipboard(owner)) { GlobalFree(memory); return false; }
  const bool copied = EmptyClipboard() && SetClipboardData(CF_DIB, memory);
  CloseClipboard();
  if (!copied) GlobalFree(memory);
  return copied;
}
}  // namespace

FlutterWindow::FlutterWindow(const flutter::DartProject& project,
                             bool initially_visible, bool quick)
    : project_(project), initially_visible_(initially_visible), quick_(quick) {
  if (!root_) root_ = this;
}

FlutterWindow::~FlutterWindow() {
  // Закрыть HWND, пока виртуальные обработчики и COM ещё доступны.
  Destroy();
}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  // Все окна принадлежат одному процессу; только корневой Dart владеет сайдкаром.
  channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "ilt/windows",
      &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler([this](const auto& call, auto result) {
    const auto& method = call.method_name();
    bool activate = true;
    const auto* options = call.arguments() ? std::get_if<flutter::EncodableMap>(call.arguments()) : nullptr;
    if (options) {
      auto requested = options->find(flutter::EncodableValue("activate"));
      if (requested != options->end()) {
        if (const auto* flag = std::get_if<bool>(&requested->second)) activate = *flag;
      }
    }
    if (method == "getWindowHandle") {
      result->Success(flutter::EncodableValue(static_cast<int64_t>(reinterpret_cast<intptr_t>(GetHandle()))));
    } else if (method == "setInitialShowState" && options) {
      auto command = options->find(flutter::EncodableValue("command"));
      auto restore = options->find(flutter::EncodableValue("restoreMaximized"));
      if (command != options->end()) {
        if (const auto* value = std::get_if<int32_t>(&command->second)) {
          if (*value == SW_SHOWNORMAL || *value == SW_SHOWMINIMIZED || *value == SW_SHOWMAXIMIZED) initial_show_ = *value;
        }
      }
      if (restore != options->end()) {
        if (const auto* value = std::get_if<bool>(&restore->second)) initial_restore_maximized_ = *value;
      }
      result->Success();
    } else if (method == "copyImage") {
      if (CopyImage(GetHandle(), call.arguments())) {
        result->Success();
      } else {
        result->Error("clipboard", "Не удалось скопировать изображение. Попробуйте ещё раз.");
      }
    } else if (method == "showQuick") {
      if (call.arguments()) root_->api_ready_ = *call.arguments();
      if (root_->quick_) {
        if (activate) root_->Activate();
        result->Success();
        return;
      }
      if (!root_->quick_window_) {
        flutter::DartProject project(L"data");
        project.set_dart_entrypoint_arguments({"--quick-view"});
        root_->quick_window_ = std::make_unique<FlutterWindow>(project, true, true);
        if (!root_->quick_window_->Create(L"Image Localization Tool — Быстрый перевод",
            Win32Window::Point(60, 60), Win32Window::Size(1000, 760))) {
          root_->quick_window_.reset();
          result->Error("window", "Не удалось открыть быстрое окно");
          return;
        }
      }
      if (activate) root_->quick_window_->Activate();
      result->Success();
    } else if (method == "getApi") {
      result->Success(root_->api_ready_);
    } else if (method == "showEditor") {
      FlutterWindow* editor = root_;
      if (root_->quick_) {
        if (call.arguments()) root_->editor_launch_ = *call.arguments();
        if (!root_->editor_window_) {
          flutter::DartProject project(L"data");
          project.set_dart_entrypoint_arguments({"--editor-view"});
          root_->editor_window_ = std::make_unique<FlutterWindow>(project, true, false);
          if (!root_->editor_window_->Create(L"Image Localization Tool",
              Win32Window::Point(10, 10), Win32Window::Size(1280, 720))) {
            root_->editor_window_.reset();
            result->Error("window", "Не удалось открыть редактор");
            return;
          }
        }
        editor = root_->editor_window_.get();
      }
      if (!root_->quick_ || root_->editor_ready_) {
        editor->channel_->InvokeMethod("activateEditor", call.arguments()
            ? std::make_unique<flutter::EncodableValue>(*call.arguments()) : nullptr);
      }
      if (activate) editor->Activate();
      result->Success();
    } else if (method == "getEditorLaunch") {
      root_->editor_ready_ = true;
      result->Success(root_->editor_launch_);
      root_->editor_launch_ = flutter::EncodableValue();
    } else if (method == "hide") {
      ShowWindow(GetHandle(), SW_HIDE);
      result->Success();
    } else if (method == "visibleEditor") {
      auto* editor = root_->quick_ ? root_->editor_window_.get() : root_;
      result->Success(flutter::EncodableValue(editor && IsWindowVisible(editor->GetHandle()) != FALSE));
    } else if (method == "visibleQuick") {
      auto* quick = root_->quick_ ? root_ : root_->quick_window_.get();
      result->Success(flutter::EncodableValue(quick && IsWindowVisible(quick->GetHandle())));
    } else if (method == "quit") {
      root_->channel_->InvokeMethod("quitRequested", nullptr);
      result->Success();
    } else if (method == "exit" && this == root_) {
      result->Success();
      PostQuitMessage(0);
    } else {
      result->NotImplemented();
    }
  });

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    first_frame_shown_ = true;
    if (initially_visible_) {
      WINDOWPLACEMENT placement{};
      placement.length = sizeof(placement);
      if (GetWindowPlacement(GetHandle(), &placement)) {
        placement.showCmd = initial_show_;
        placement.flags = initial_restore_maximized_ ? WPF_RESTORETOMAXIMIZED : 0;
        SetWindowPlacement(GetHandle(), &placement);
      } else {
        ShowWindow(GetHandle(), initial_show_);
      }
    }
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  // Дочерний engine закрывается до корневого.
  quick_window_.reset();
  editor_window_.reset();
  channel_.reset();
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

void FlutterWindow::Activate() {
  if (!first_frame_shown_) return;
  ShowWindow(GetHandle(), IsIconic(GetHandle()) ? SW_RESTORE : SW_SHOW);
  SetForegroundWindow(GetHandle());
  if (channel_) channel_->InvokeMethod("windowActivated", nullptr);
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Закрытие решает координатор, чтобы не остановить общую очередь с другим окном.
  if (message == WM_CLOSE && channel_) {
    channel_->InvokeMethod("closeRequested", nullptr);
    return 0;
  }
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      if (flutter_controller_) flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
