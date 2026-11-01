/// История правок одной страницы (снимки документа).
class HistoryEntry {
  HistoryEntry(this.snapshot, this.bytes);

  final Map<String, dynamic> snapshot;
  final int bytes;
}

class PageHistory {
  final List<HistoryEntry> past = [];
  final List<HistoryEntry> future = [];
  int pastBytes = 0;
  int futureBytes = 0;
  static const limit = 1000;
  static const maxBytes = 256 * 1024 * 1024;

  void addPast(Map<String, dynamic> snapshot, int bytes) {
    past.add(HistoryEntry(snapshot, bytes));
    pastBytes += bytes;
    _trim(past, pastBytes, (value) => pastBytes = value);
  }

  void addFuture(Map<String, dynamic> snapshot, int bytes) {
    future.add(HistoryEntry(snapshot, bytes));
    futureBytes += bytes;
    _trim(future, futureBytes, (value) => futureBytes = value);
  }

  HistoryEntry popPast() {
    final entry = past.removeLast();
    pastBytes -= entry.bytes;
    return entry;
  }

  HistoryEntry popFuture() {
    final entry = future.removeLast();
    futureBytes -= entry.bytes;
    return entry;
  }

  void clearFuture() {
    future.clear();
    futureBytes = 0;
  }

  static void _trim(
    List<HistoryEntry> entries,
    int bytes,
    void Function(int) setBytes,
  ) {
    var total = bytes;
    while (entries.length > limit || (total > maxBytes && entries.length > 1)) {
      total -= entries.removeAt(0).bytes;
    }
    setBytes(total);
  }
}
