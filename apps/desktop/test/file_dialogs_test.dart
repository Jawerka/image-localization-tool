import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/ui/file_dialogs.dart';

void main() {
  test('диалог страниц совпадает с форматами sidecar', () {
    expect(
      pageFileExtensions,
      [
        'png',
        'jpg',
        'jpeg',
        'bmp',
        'tif',
        'tiff',
        'zip',
        'cbz',
        'cbr',
        'rar',
        'cb7',
        '7z',
        'cbt',
        'tar',
      ],
    );
    expect(pageFileExtensions.contains('gif'), isFalse);
    expect(pageFileExtensions.contains('webp'), isFalse);
  });
}
