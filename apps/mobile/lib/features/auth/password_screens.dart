import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/auth/auth_validators.dart';
import 'package:factory_finder/features/auth/password_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

String? _tr(BuildContext context, String? key) =>
    key == null ? null : context.tr(key);

void _snack(BuildContext context, String text) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}

/// Asks for the email and always shows the same neutral confirmation, so the
/// screen never reveals whether the account exists.
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  bool _busy = false;
  bool _sent = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(passwordRepositoryProvider).forgot(_email.text.trim());
      if (mounted) setState(() => _sent = true);
    } catch (e) {
      if (mounted) _snack(context, localizedPasswordError(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('auth.forgot.title'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Text(
              context.tr('auth.forgot.intro'),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('forgot-email'),
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: InputDecoration(labelText: context.tr('auth.email')),
              validator: (v) => _tr(context, validateEmail(v)),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('auth.forgot.send'),
              loading: _busy,
              onPressed: _submit,
            ),
            if (_sent) ...[
              const SizedBox(height: AppSpacing.md),
              Container(
                key: const ValueKey<String>('forgot-sent'),
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: AppColors.primary.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Text(context.tr('auth.forgot.sent')),
              ),
            ],
            TextButton(
              key: const ValueKey<String>('forgot-have-code'),
              onPressed: () => context.push('/reset-password'),
              child: Text(context.tr('auth.forgot.have_code')),
            ),
          ],
        ),
      ),
    );
  }
}

/// Reset with the pasted token (or one passed as `?token=`) and a new password.
class ResetPasswordScreen extends ConsumerStatefulWidget {
  const ResetPasswordScreen({super.key, this.initialToken});

  final String? initialToken;

  @override
  ConsumerState<ResetPasswordScreen> createState() => _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends ConsumerState<ResetPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _token =
      TextEditingController(text: widget.initialToken ?? '');
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _token.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(passwordRepositoryProvider).reset(
            token: _token.text.trim(),
            newPassword: _password.text,
          );
      if (!mounted) return;
      _snack(context, context.tr('auth.reset.done'));
      context.go('/login');
    } catch (e) {
      if (mounted) _snack(context, localizedPasswordError(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('auth.reset.title'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            TextFormField(
              key: const ValueKey<String>('reset-token'),
              controller: _token,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(labelText: context.tr('auth.reset.token')),
              validator: (v) => _tr(context, validateResetToken(v)),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('reset-password'),
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(
                labelText: context.tr('auth.reset.new_password'),
                helperText: context.tr('auth.password_hint'),
              ),
              validator: (v) => _tr(context, validateNewPassword(v)),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('reset-confirm'),
              controller: _confirm,
              obscureText: true,
              decoration: InputDecoration(labelText: context.tr('auth.reset.confirm')),
              validator: (v) => _tr(context, validatePasswordConfirm(v, _password.text)),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('auth.reset.submit'),
              loading: _busy,
              onPressed: _submit,
            ),
          ],
        ),
      ),
    );
  }
}

/// Signed-in password change (current + new + confirm).
class ChangePasswordScreen extends ConsumerStatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  ConsumerState<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _current = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _current.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(passwordRepositoryProvider).change(
            currentPassword: _current.text,
            newPassword: _password.text,
          );
      if (!mounted) return;
      _snack(context, context.tr('auth.change.done'));
      if (context.canPop()) context.pop();
    } catch (e) {
      if (mounted) _snack(context, localizedPasswordError(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('auth.change.title'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            TextFormField(
              key: const ValueKey<String>('change-current'),
              controller: _current,
              obscureText: true,
              decoration: InputDecoration(labelText: context.tr('auth.change.current')),
              validator: (v) => _tr(context, validateCurrentPassword(v)),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('change-password'),
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(
                labelText: context.tr('auth.reset.new_password'),
                helperText: context.tr('auth.password_hint'),
              ),
              validator: (v) =>
                  _tr(context, validateNewPassword(v, current: _current.text)),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('change-confirm'),
              controller: _confirm,
              obscureText: true,
              decoration: InputDecoration(labelText: context.tr('auth.reset.confirm')),
              validator: (v) => _tr(context, validatePasswordConfirm(v, _password.text)),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('auth.change.title'),
              loading: _busy,
              onPressed: _submit,
            ),
          ],
        ),
      ),
    );
  }
}
