import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/router/return_path.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/auth/auth_validators.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Validated `from` query parameter of the current /login or /register page.
String? _returnPath(BuildContext context) =>
    sanitizeReturnPath(GoRouterState.of(context).uri.queryParameters['from']);

/// Same-screen switch (login <-> register) that keeps the return path.
String _switchTo(BuildContext context, String path) {
  final from = _returnPath(context);
  return from == null
      ? path
      : Uri(path: path, queryParameters: {'from': from}).toString();
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(authProvider.notifier).login(
            email: _email.text.trim(),
            password: _password.text,
          );
      if (!mounted) return;
      // Redirected from a protected route: return there (validated).
      final from = _returnPath(context);
      if (from != null) {
        context.go(from);
        return;
      }
      // Deep-linked /login has nothing to pop; fall back to the home tab.
      if (context.canPop()) {
        context.pop();
      } else {
        context.go('/discover');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(localizedError(context, e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('auth.login'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if (kMockMode)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: Text(
                  context.tr('auth.mock_note'),
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              ),
            TextFormField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: InputDecoration(labelText: context.tr('auth.email')),
              validator: (v) {
                final k = validateEmail(v);
                return k == null ? null : context.tr(k);
              },
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(labelText: context.tr('auth.password')),
              validator: (v) {
                final k = validatePassword(v);
                return k == null ? null : context.tr(k);
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('auth.login'),
              loading: _busy,
              onPressed: _submit,
            ),
            TextButton(
              key: const ValueKey<String>('login-forgot'),
              onPressed: () => context.push('/forgot-password'),
              child: Text(context.tr('auth.forgot_link')),
            ),
            TextButton(
              onPressed: () => context.pushReplacement(_switchTo(context, '/register')),
              child: Text(context.tr('auth.no_account')),
            ),
          ],
        ),
      ),
    );
  }
}

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref.read(authProvider.notifier).register(
            name: _name.text.trim(),
            email: _email.text.trim(),
            phone: _phone.text.trim().isEmpty ? null : _phone.text.trim(),
            password: _password.text,
          );
      if (!mounted) return;
      // Redirected from a protected route: return there (validated).
      final from = _returnPath(context);
      if (from != null) {
        context.go(from);
        return;
      }
      // Deep-linked /login has nothing to pop; fall back to the home tab.
      if (context.canPop()) {
        context.pop();
      } else {
        context.go('/discover');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(localizedError(context, e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('auth.register'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            TextFormField(
              controller: _name,
              decoration: InputDecoration(labelText: context.tr('auth.name')),
              validator: (v) {
                final k = validateName(v);
                return k == null ? null : context.tr(k);
              },
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: InputDecoration(labelText: context.tr('auth.email')),
              validator: (v) {
                final k = validateEmail(v);
                return k == null ? null : context.tr(k);
              },
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: InputDecoration(labelText: context.tr('auth.phone')),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(labelText: context.tr('auth.password')),
              validator: (v) {
                final k = validatePassword(v);
                return k == null ? null : context.tr(k);
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('auth.register'),
              loading: _busy,
              onPressed: _submit,
            ),
            TextButton(
              onPressed: () => context.pushReplacement(_switchTo(context, '/login')),
              child: Text(context.tr('auth.have_account')),
            ),
          ],
        ),
      ),
    );
  }
}
