import 'package:file_selector/file_selector.dart';

/// Обёртки системных диалогов выбора путей (file_selector).
///
/// В `--api` режиме серверные диалоги недоступны (DialogBridge-заглушка),
/// поэтому пути выбирает сам хост и отправляет их в API.

const XTypeGroup _pageGroup = XTypeGroup(
  label: 'Страницы и архивы',
  extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tif', 'tiff', 'cbz', 'cbr', 'zip'],
);

const XTypeGroup _packageGroup = XTypeGroup(
  label: 'Проект ILT',
  extensions: ['zip'],
);

/// Выбрать файлы страниц. Пустой список — отмена.
Future<List<String>> pickFiles() async {
  final files = await openFiles(acceptedTypeGroups: const [_pageGroup]);
  return [for (final file in files) file.path];
}

/// Выбрать папку со страницами. null — отмена.
Future<String?> pickFolder() => getDirectoryPath();

/// Выбрать портативный проект для загрузки. null — отмена.
Future<String?> pickPackageToOpen() async {
  final file = await openFile(acceptedTypeGroups: const [_packageGroup]);
  return file?.path;
}

/// Выбрать место сохранения проекта. null — отмена.
Future<String?> pickPackageToSave(String suggestedName) async {
  final location = await getSaveLocation(
    suggestedName: suggestedName,
    acceptedTypeGroups: const [_packageGroup],
  );
  return location?.path;
}
