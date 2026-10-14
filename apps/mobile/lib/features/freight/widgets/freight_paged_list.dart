import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Keyset-paginated list (load-more button) that reloads whenever
/// [freightRefreshProvider] changes. Recreate it with a new key to reset
/// (e.g. when a filter changes).
class FreightPagedList<T> extends ConsumerStatefulWidget {
  const FreightPagedList({
    super.key,
    required this.fetch,
    required this.itemBuilder,
    required this.emptyTitle,
    this.emptyMessage,
    this.emptyIcon = Icons.inbox_outlined,
    this.header = const [],
    this.idPrefix = 'freight_list',
  });

  final Future<FreightPage<T>> Function(String? cursor) fetch;
  final Widget Function(BuildContext context, T item) itemBuilder;
  final String emptyTitle;
  final String? emptyMessage;
  final IconData emptyIcon;

  /// Scrolls with the list (buttons, filters).
  final List<Widget> header;
  final String idPrefix;

  @override
  ConsumerState<FreightPagedList<T>> createState() => _FreightPagedListState<T>();
}

class _FreightPagedListState<T> extends ConsumerState<FreightPagedList<T>> {
  final List<T> _items = <T>[];
  String? _cursor;
  bool _hasMore = false;
  bool _loading = true;
  bool _loadingMore = false;
  Object? _error;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final gen = ++_generation;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.fetch(null);
      if (!mounted || gen != _generation) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _more() async {
    if (_loadingMore || !_hasMore) return;
    final gen = _generation;
    setState(() {
      _loadingMore = true;
      _error = null;
    });
    try {
      final page = await widget.fetch(_cursor);
      if (!mounted || gen != _generation) return;
      setState(() {
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loadingMore = false;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() {
        _error = e;
        _loadingMore = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(freightRefreshProvider, (previous, next) => _load());
    final id = widget.idPrefix;
    final children = <Widget>[...widget.header];
    if (_loading && _items.isEmpty) {
      children.add(Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Center(
          child: CircularProgressIndicator(key: ValueKey<String>('${id}_loading')),
        ),
      ));
    } else if (_error != null && _items.isEmpty) {
      children.add(SizedBox(
        key: ValueKey<String>('${id}_error'),
        child: ErrorState(
          message: context.freightError(_error!),
          error: _error,
          onRetry: _load,
        ),
      ));
    } else if (_items.isEmpty) {
      children.add(SizedBox(
        key: ValueKey<String>('${id}_empty'),
        child: EmptyState(
          icon: widget.emptyIcon,
          title: widget.emptyTitle,
          message: widget.emptyMessage,
        ),
      ));
    } else {
      for (final item in _items) {
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: widget.itemBuilder(context, item),
        ));
      }
      if (_error != null) {
        children.add(FreightErrorBox(context.freightError(_error!)));
      }
      if (_hasMore) {
        children.add(OutlinedButton(
          key: ValueKey<String>('${id}_load_more'),
          style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
          onPressed: _loadingMore ? null : _more,
          child: _loadingMore
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Text(context.tr('freight.load_more')),
        ));
      }
    }
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: children,
    );
  }
}
