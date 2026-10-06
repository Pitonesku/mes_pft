// lib/core/hash_navigation_stub.dart
/// Non-web (Android/desktop) no-op implementation.

void listenToHashChange(void Function(String fragment) callback) {}

String currentHash() => '';

/// Non-web no-op: there is no browser hash to update.
void setHash(String fragment) {}

void navigateTo(String path) {}
