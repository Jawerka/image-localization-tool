import 'dart:async';

import 'package:flutter/material.dart';

import '../../state/shell_state.dart';
import '../theme.dart';
import '../widgets.dart';

/// Экран «Доступ по сети»: включение, код сопряжения и устройства.
class RemoteScreen extends StatefulWidget {
  const RemoteScreen({super.key, required this.state});

  final ShellState state;

  @override
  State<RemoteScreen> createState() => _RemoteScreenState();
}

class _RemoteScreenState extends State<RemoteScreen> {
  late bool _enabled;
  late String _bind;
  late int _port;
  bool _applying = false;

  ShellState get state => widget.state;

  @override
  void initState() {
    super.initState();
    final settings = state.workspace.settings;
    _enabled = settings['remote_enabled'] == true;
    _bind = '${settings['remote_bind'] ?? '0.0.0.0'}';
    final port = settings['remote_port'];
    _port = port is num ? port.toInt() : 8765;
    unawaited(state.secondary.refreshRemote());
  }

  Future<void> _applyNetwork() async {
    setState(() => _applying = true);
    await state.workspace.updateSettings({
      'remote_enabled': _enabled,
      'remote_bind': _bind,
      'remote_port': _port,
    });
    if (!mounted) return;
    setState(() => _applying = false);
    _toast('Настройки сети сохранены — применится после перезапуска API');
  }

  Future<void> _restart() async {
    await state.restartSidecar();
    await state.secondary.refreshRemote();
    if (mounted) _toast('API перезапущен');
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 3)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) {
        final remote = state.secondary.remote;
        return Container(
          key: const Key('remote-screen'),
          color: palette.bgPrimary,
          child: Column(
            children: [
              Container(
                height: 46,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(
                  color: palette.surface1,
                  border: Border(bottom: BorderSide(color: palette.line)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.public, size: 16, color: palette.primary),
                    const SizedBox(width: 8),
                    Text('Доступ по сети', style: theme.textTheme.titleSmall),
                    const SizedBox(width: 12),
                    Text(
                      'страницы открываются в браузере соседнего устройства',
                      style: theme.textTheme.labelSmall,
                    ),
                    const Spacer(),
                    IconButton(
                      key: const Key('remote-close'),
                      tooltip: 'Закрыть (Esc)',
                      iconSize: 16,
                      onPressed: () => state.closeOverlay(),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 720),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          PanelCard(
                            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                IltSwitchRow(
                                  label: 'Разрешить доступ в локальной сети',
                                  value: _enabled,
                                  onChanged: (value) =>
                                      setState(() => _enabled = value),
                                ),
                                FieldRow(
                                  label: 'Адрес',
                                  child: IltTextField(
                                    value: _bind,
                                    onChanged: (value) =>
                                        setState(() => _bind = value),
                                  ),
                                ),
                                FieldRow(
                                  label: 'Порт',
                                  child: IltNumberField(
                                    value: _port,
                                    min: 1,
                                    max: 65535,
                                    onChanged: (value) =>
                                        setState(() => _port = value.toInt()),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Row(
                                  children: [
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 8,
                                        vertical: 3,
                                      ),
                                      decoration: BoxDecoration(
                                        color: palette.surface2,
                                        borderRadius: BorderRadius.circular(10),
                                        border:
                                            Border.all(color: palette.border),
                                      ),
                                      child: Text(
                                        remote.enabled
                                            ? 'слушает ${remote.addresses.isEmpty ? '…' : remote.addresses.join(', ')}'
                                            : 'не слушает',
                                        style: theme.textTheme.labelSmall,
                                      ),
                                    ),
                                    const Spacer(),
                                    OutlinedButton(
                                      key: const Key('remote-save'),
                                      onPressed: _applying ? null : _applyNetwork,
                                      child: const Text('Сохранить'),
                                    ),
                                    const SizedBox(width: 8),
                                    FilledButton(
                                      key: const Key('remote-restart'),
                                      onPressed: _restart,
                                      child: const Text('Перезапустить API'),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                          PanelCard(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Код сопряжения',
                                  style: theme.textTheme.labelMedium,
                                ),
                                const SizedBox(height: 6),
                                Row(
                                  children: [
                                    Text(
                                      remote.pairingCode.isEmpty
                                          ? '— — — — — —'
                                          : remote.pairingCode,
                                      key: const Key('remote-code'),
                                      style: theme.textTheme.titleSmall
                                          ?.copyWith(
                                        fontSize: 22,
                                        letterSpacing: 2,
                                        color: palette.textPrimary,
                                      ),
                                    ),
                                    const SizedBox(width: 16),
                                    OutlinedButton(
                                      key: const Key('remote-new-code'),
                                      onPressed: remote.enabled
                                          ? state.secondary.issuePairCode
                                          : null,
                                      child: const Text('Новый код'),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  'Показан тому, кто открывает адрес — один раз на устройство',
                                  style: theme.textTheme.labelSmall,
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                          PanelCard(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  'Подключённые устройства',
                                  style: theme.textTheme.labelMedium,
                                ),
                                const SizedBox(height: 8),
                                if (remote.devices.isEmpty)
                                  Text(
                                    'Пока никто не подключён',
                                    key: const Key('remote-no-devices'),
                                    style: theme.textTheme.bodySmall,
                                  )
                                else
                                  for (final device in remote.devices)
                                    Padding(
                                      padding:
                                          const EdgeInsets.only(bottom: 6),
                                      child: Row(
                                        children: [
                                          Icon(
                                            Icons.phone_iphone,
                                            size: 14,
                                            color: palette.textMuted,
                                          ),
                                          const SizedBox(width: 8),
                                          Expanded(
                                            child: Text(
                                              device.name.isEmpty
                                                  ? device.id
                                                  : device.name,
                                              overflow: TextOverflow.ellipsis,
                                              style: theme.textTheme.bodySmall
                                                  ?.copyWith(
                                                color: palette.textPrimary,
                                              ),
                                            ),
                                          ),
                                          SizedBox(
                                            width: 140,
                                            child: Text(
                                              device.address,
                                              style:
                                                  theme.textTheme.labelSmall,
                                            ),
                                          ),
                                          SizedBox(
                                            width: 110,
                                            child: Text(
                                              device.active
                                                  ? 'активен сейчас'
                                                  : 'неактивен',
                                              style:
                                                  theme.textTheme.labelSmall,
                                            ),
                                          ),
                                          OutlinedButton(
                                            key: Key(
                                              'remote-revoke-${device.id}',
                                            ),
                                            onPressed: () => state
                                                .secondary
                                                .revokeDevice(device.id),
                                            child: const Text('Отозвать'),
                                          ),
                                        ],
                                      ),
                                    ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            'Брандмауэр Windows может блокировать порт. '
                            'Передача идёт по обычному HTTP без шифрования — '
                            'не публикуйте адрес за пределами квартиры или офиса.',
                            style: theme.textTheme.labelSmall
                                ?.copyWith(color: palette.textWarning),
                          ),
                          const SizedBox(height: 12),
                          PanelCard(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Что видит устройство',
                                  style: theme.textTheme.labelMedium,
                                ),
                                const SizedBox(height: 6),
                                _kv(context, 'Редактор и просмотр', 'да'),
                                _kv(context, 'Перевод страниц', 'да'),
                                _kv(
                                  context,
                                  'Экспорт на диск сервера',
                                  'нет',
                                ),
                                _kv(context, 'Доступ к настройкам', 'нет'),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: palette.surface1,
                  border: Border(top: BorderSide(color: palette.line)),
                ),
                child: Row(
                  children: [
                    Text(
                      'Отключение доступа разрывает активные сессии сразу.',
                      style: theme.textTheme.labelSmall,
                    ),
                    const Spacer(),
                    FilledButton(
                      key: const Key('remote-done'),
                      onPressed: () => state.closeOverlay(),
                      child: const Text('Готово'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _kv(BuildContext context, String key, String value) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(child: Text(key, style: theme.textTheme.bodySmall)),
          Text(value, style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }
}
