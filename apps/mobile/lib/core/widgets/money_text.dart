import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:flutter/material.dart';

class MoneyText extends StatelessWidget {
  const MoneyText(Money this.money, {super.key, this.style}) : range = null;

  const MoneyText.range(MoneyRange this.range, {super.key, this.style})
      : money = null;

  final Money? money;
  final MoneyRange? range;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final raw = money != null ? money!.format() : (range?.format() ?? '');
    final text = localizeNumber(raw, DigitStyleScope.of(context));
    // Numbers/currency are always laid out left-to-right, even inside RTL text.
    return Directionality(
      textDirection: TextDirection.ltr,
      child: Text(
        text,
        style: style ?? const TextStyle(fontWeight: FontWeight.w700),
      ),
    );
  }
}
