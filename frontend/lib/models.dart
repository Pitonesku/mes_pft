// models.dart
// Файл Моделей данных. В этом файле нет никакого интерфейса, 
// только описания объектов (Пользователь, Заказ, Смена)

import 'package:flutter/material.dart';

enum UserRole { operator, manager, superAdmin }
enum MaterialCategory { acetate, paper, coldGlue, hotMelt, triacetin }

class User {
  int? id;
  String name;
  String password;
  String email;
  UserRole role;
  bool canModifyPO;
  bool isInactive; // Новая галочка: Не активен

  User({
    this.id,
    required this.name,
    required this.password,
    required this.email,
    required this.role,
    this.canModifyPO = false,
    this.isInactive = false,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    // Определяем роль на основе role_id от сервера (например: 1 - админ, 2 - менеджер, 3 - оператор)
    UserRole parsedRole = UserRole.operator;
    if (json['role_id'] == 1) parsedRole = UserRole.superAdmin;
    if (json['role_id'] == 2) parsedRole = UserRole.manager;

    return User(
      id: json['id'],
      name: json['username'] ?? 'Unknown',
      password: json['password_hash'] ?? '',
      email: json['email'] ?? '',
      role: parsedRole,
      canModifyPO: json['role_id'] == 1 || json['role_id'] == 2,
      isInactive: json['is_inactive'] ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'username': name,
      'password': password,
      'email': email,
      'role_id': _getRoleId(role),
      'is_inactive': isInactive,
    };
  }

  Map<String, dynamic> toUpdateJson() {
    final data = {
      'username': name,
      'email': email,
      'role_id': _getRoleId(role),
      'is_inactive': isInactive,
    };

    if (password.isNotEmpty) {
      data['password'] = password;
    }

    return data;
  }

    // Вспомогательный метод для получения ID роли
  int _getRoleId(UserRole role) {
    switch (role) {
      case UserRole.superAdmin: return 1;
      case UserRole.manager: return 2;
      case UserRole.operator: return 3;
    }
  }
}

class PurchaseOrder {
  final int? id;
  final String poNumber;
  final DateTime createdAt; // Дата создания
  final double diameter;
  final double length;
  final double pd;
  final int cu; // Пористость (вернули)
  final double weight;
  final int boxType;
  
  final String acetateType;
  final String paperType;
  final String hmGlueType;
  final String pvaGlueType;
  final String triacetinType;

  final int targetQty; // Необходимое кол-во (в штуках)
  int producedQty; // Готовое кол-во
  bool isHidden; // Скрыть от операторов
  bool isArchived; // Архивный заказ

  

  PurchaseOrder({
    this.id,
    required this.poNumber, required this.createdAt, 
    required this.diameter, required this.length, required this.pd, 
    required this.cu, required this.weight, required this.boxType,
    required this.acetateType, required this.paperType, 
    required this.hmGlueType, required this.pvaGlueType, required this.triacetinType,
    required this.targetQty, this.producedQty = 0, this.isHidden = false,
    this.isArchived = false,
  });

  int get remainingQty => targetQty - producedQty;

  factory PurchaseOrder.fromJson(Map<String, dynamic> json) {
    return PurchaseOrder(
      id: json['id'],
      poNumber: json['po_number'] ?? 'Unknown',
      diameter: (json['diameter'] ?? 0).toDouble(),
      length: (json['length'] ?? 0).toDouble(),
      pd: (json['pd'] ?? 0).toDouble(),
      cu: json['cu'] ?? 0,
      weight: (json['weight'] ?? 0).toDouble(),
      boxType: json['box_type'] ?? 0,
      acetateType: json['acetate_type'] ?? '',
      paperType: json['paper_type'] ?? '',
      pvaGlueType: json['pva_glue_type'] ?? '',
      hmGlueType: json['hm_glue_type'] ?? '',
      triacetinType: json['triacetin_type'] ?? '',
      isHidden: json['is_hidden'] ?? false,
      isArchived: json['is_archived'] ?? false,
      
      // Добавленные обязательные поля:
      targetQty: json['target_qty'] ?? 0,
      producedQty: json['produced_qty'] ?? 0,
      
      // Конвертируем строку с датой от FastAPI обратно в объект DateTime
      createdAt: json['created_at'] != null 
          ? DateTime.tryParse(json['created_at']) ?? DateTime.now() 
          : DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() => {
    'po_number': poNumber,
    'diameter': diameter,
    'length': length,
    'pd': pd,
    'cu': cu,
    'weight': weight,
    'box_type': boxType,
    'acetate_type': acetateType,
    'paper_type': paperType,
    'pva_glue_type': pvaGlueType,
    'hm_glue_type': hmGlueType,
    'triacetin_type': triacetinType,
    'is_hidden': isHidden,
    'is_archived': isArchived,
    'target_qty': targetQty,
    'produced_qty': producedQty,
    'created_at': createdAt.toIso8601String(),
  };

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is PurchaseOrder && runtimeType == other.runtimeType && poNumber == other.poNumber;

  @override
  int get hashCode => poNumber.hashCode;
}

class Machine {
  String name;
  String remarks;
  bool isInactive;

  Machine({required this.name, this.remarks = "", this.isInactive = false});
  
  factory Machine.fromJson(Map<String, dynamic> json) {
    return Machine(
      name: json['name'] ?? 'Unknown',
      // В Python у нас is_inactive, поэтому читаем его
      isInactive: json['is_inactive'] ?? false, 
    );
    
  }

  Map<String, dynamic> toJson() => {
    'name': name,
    'is_inactive': isInactive,
    'remarks': remarks,
  };

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Machine && runtimeType == other.runtimeType && name == other.name;

  @override
  int get hashCode => name.hashCode;
}

class Shift {
  String name;
  String start;
  String end;
  
  Shift({required this.name, required this.start, required this.end});

  
  factory Shift.fromJson(Map<String, dynamic> json) => Shift(
    name: json['name'] ?? '',
    start: json['start'] ?? '',
    end: json['end'] ?? '',
  );

  Map<String, dynamic> toJson() => {
    'name': name,
    'start': start,
    'end': end,
  };
  

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Shift && runtimeType == other.runtimeType && name == other.name;

  @override
  int get hashCode => name.hashCode;
}

class RawMaterial {
  MaterialCategory category;
  String type;
  String? batch; // Батч не обязателен
  bool isHidden;

  RawMaterial({
    required this.category, required this.type, 
    this.batch, this.isHidden = false
  });

  factory RawMaterial.fromJson(Map<String, dynamic> json) {
  // Простейший парсер категории (адаптируйте под ваши значения в базе)
  MaterialCategory parsedCategory = MaterialCategory.acetate;
  String catStr = (json['category'] ?? '').toString().toLowerCase();
  if (catStr.contains('paper')) parsedCategory = MaterialCategory.paper;
  if (catStr.contains('hot')) parsedCategory = MaterialCategory.hotMelt;
  if (catStr.contains('cold') || catStr.contains('pva')) parsedCategory = MaterialCategory.coldGlue;
  if (catStr.contains('triacetin')) parsedCategory = MaterialCategory.triacetin;

  return RawMaterial(
    category: parsedCategory,
    type: json['type_name'] ?? 'Unknown', // Зависит от названия колонки в FastAPI
    batch: json['default_batch'] ?? '', 
    isHidden: json['is_hidden'] ?? false,
  );
  }
  Map<String, dynamic> toJson() => {
    'category': category.toString().split('.').last, // Сохраняем категорию как строку
    'type_name': type,
    'default_batch': batch,
    'is_hidden': isHidden,
  };
}

class MaterialItem {
  final TextEditingController type;
  final TextEditingController batch;
  final TextEditingController start;
  final TextEditingController stop;
  double used;

  MaterialItem({String defaultType = ""})
      : type = TextEditingController(text: defaultType),
        batch = TextEditingController(),
        start = TextEditingController(),
        stop = TextEditingController(),
        used = 0.0;

  // Формула расчета расхода (Начало минус Конец)
  void calculateUsed() {
    double s = double.tryParse(start.text.replaceAll(',', '.')) ?? 0;
    double e = double.tryParse(stop.text.replaceAll(',', '.')) ?? 0;
    used = s - e;
  }

  // СОХРАНЕНИЕ: Превращаем объект в JSON для базы данных
  Map<String, dynamic> toJson() {
    return {
      'type': type.text,
      'batch': batch.text,
      'start': start.text,
      'stop': stop.text,
      'used': used,
    };
  }

  // ЗАГРУЗКА: Восстанавливаем объект из JSON
  factory MaterialItem.fromJson(Map<String, dynamic> json) {
    final item = MaterialItem(defaultType: json['type'] ?? '');
    item.batch.text = json['batch'] ?? '';
    item.start.text = json['start'] ?? '';
    item.stop.text = json['stop'] ?? '';
    item.used = (json['used'] as num?)?.toDouble() ?? 0.0;
    return item;
  }

  void dispose() {
    type.dispose();
    batch.dispose();
    start.dispose();
    stop.dispose();
  }
}