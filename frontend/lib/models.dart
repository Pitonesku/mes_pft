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
  bool canManageQuality; // create/close NCRs, scrap & release quarantine boxes

  User({
    this.id,
    required this.name,
    required this.password,
    required this.email,
    required this.role,
    this.canModifyPO = false,
    this.isInactive = false,
    this.canManageQuality = false,
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
      canManageQuality: json['can_manage_quality'] ?? false,
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
  final double? diameterTolerance; // ± tolerance override for diameter
  final double? pdTolerance;       // ± tolerance override for pressure drop
  final double triacetin;          // target triacetin content (%)
  final double? triacetinTolerance; // ± tolerance (percentage points)
  final String source;              // 'odoo' | 'local'
  final Map<String, dynamic>? allowedMaterials; // category -> [{material_id, product_name}]
  final int? odooMoId;              // root mrp.production id
  final String? odooMoName;         // root MO name (e.g. WH/MO/00217)
  
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
    this.diameterTolerance, this.pdTolerance,
    this.triacetin = 0, this.triacetinTolerance,
    this.source = 'local', this.allowedMaterials,
    this.odooMoId, this.odooMoName,
  });

  /// Manufacturing Order number (terminology alias of the legacy poNumber).
  String get moNumber => poNumber;

  /// True when this MO is linked to an Odoo Manufacturing Order.
  bool get isOdooLinked => odooMoId != null || source == 'odoo';

  int get remainingQty => targetQty - producedQty;

  factory PurchaseOrder.fromJson(Map<String, dynamic> json) {
    return PurchaseOrder(
      id: json['id'],
      poNumber: json['mo_number'] ?? json['po_number'] ?? 'Unknown',
      diameter: (json['diameter'] ?? 0).toDouble(),
      length: (json['length'] ?? 0).toDouble(),
      pd: (json['pd'] ?? 0).toDouble(),
      cu: json['cu'] ?? 0,
      weight: (json['weight'] ?? 0).toDouble(),
      boxType: json['box_type'] ?? 0,
      diameterTolerance: (json['diameter_tolerance'] as num?)?.toDouble(),
      pdTolerance: (json['pd_tolerance'] as num?)?.toDouble(),
      triacetin: (json['triacetin'] ?? 0).toDouble(),
      triacetinTolerance: (json['triacetin_tolerance'] as num?)?.toDouble(),
      acetateType: json['acetate_type'] ?? '',
      paperType: json['paper_type'] ?? '',
      pvaGlueType: json['pva_glue_type'] ?? '',
      hmGlueType: json['hm_glue_type'] ?? '',
      triacetinType: json['triacetin_type'] ?? '',
      isHidden: json['is_hidden'] ?? false,
      isArchived: json['is_archived'] ?? false,
      source: json['source'] ?? 'local',
      allowedMaterials: json['allowed_materials'] as Map<String, dynamic>?,
      odooMoId: json['odoo_mo_id'],
      odooMoName: json['odoo_mo_name'],
      
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
    if (diameterTolerance != null) 'diameter_tolerance': diameterTolerance,
    if (pdTolerance != null) 'pd_tolerance': pdTolerance,
    if (triacetin != 0) 'triacetin': triacetin,
    if (triacetinTolerance != null) 'triacetin_tolerance': triacetinTolerance,
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
  int? id;
  String name;
  String remarks;
  bool isInactive;

  Machine({this.id, required this.name, this.remarks = "", this.isInactive = false});
  
  factory Machine.fromJson(Map<String, dynamic> json) {
    return Machine(
      id: json['id'],
      name: json['name'] ?? 'Unknown',
      remarks: json['remarks'] ?? "",
      // В Python у нас is_inactive, поэтому читаем его
      isInactive: json['is_inactive'] ?? false, 
    );
  }

  Map<String, dynamic> toJson() => {
    if (id != null) 'id': id,
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
  int? odooProductId; // mapped Odoo product.product id
  String source;       // 'odoo' | 'local'

  RawMaterial({
    required this.category, required this.type, 
    this.batch, this.isHidden = false,
    this.odooProductId, this.source = 'local',
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
    odooProductId: json['odoo_product_id'],
    source: json['source'] ?? 'local',
  );
  }
  Map<String, dynamic> toJson() => {
    'category': category.toString().split('.').last, // Сохраняем категорию как строку
    'type_name': type,
    'default_batch': batch,
    'is_hidden': isHidden,
    if (odooProductId != null) 'odoo_product_id': odooProductId,
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

// ---------------------------------------------------------------------------
// Quality management (NCR + quarantine)
// ---------------------------------------------------------------------------

class Ncr {
  final int id;
  final String? ncrNumber;
  final int poId;
  final String? moRef;
  final int? machineId;
  final String? machineName;
  final String description;
  final String? correctiveAction;
  final String severity;
  final String status;
  final DateTime? createdAt;
  final int? closedBy;
  final DateTime? closedAt;
  final String? closingRemarks;
  final List<Map<String, dynamic>> history;

  Ncr({
    required this.id, this.ncrNumber, required this.poId, this.moRef,
    this.machineId, this.machineName, required this.description,
    this.correctiveAction, this.severity = 'MINOR', this.status = 'OPEN',
    this.createdAt, this.closedBy, this.closedAt, this.closingRemarks,
    this.history = const [],
  });

  bool get isOpen => status == 'OPEN' || status == 'IN_PROGRESS';
  bool get isCritical => severity == 'CRITICAL';

  factory Ncr.fromJson(Map<String, dynamic> json) => Ncr(
    id: json['id'],
    ncrNumber: json['ncr_number'],
    poId: json['po_id'],
    moRef: json['mo_ref'],
    machineId: json['machine_id'],
    machineName: json['machine_name'],
    description: json['description'] ?? '',
    correctiveAction: json['corrective_action'],
    severity: json['severity'] ?? 'MINOR',
    status: json['status'] ?? 'OPEN',
    createdAt: json['created_at'] != null ? DateTime.tryParse(json['created_at']) : null,
    closedBy: json['closed_by'],
    closedAt: json['closed_at'] != null ? DateTime.tryParse(json['closed_at']) : null,
    closingRemarks: json['closing_remarks'],
    history: (json['history'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>(),
  );
}

class QuarantineResolution {
  final int id;
  final String? docNumber;
  final int poId;
  final String? moRef;
  final String kind; // scrap | release
  final int boxes;
  final double? dryWeightKg;
  final String? reasonCode;
  final String? notes;
  final int? ncrId;
  final String odooSyncStatus;
  final DateTime? createdAt;
  final DateTime? voidedAt;

  QuarantineResolution({
    required this.id, this.docNumber, required this.poId, this.moRef,
    required this.kind, required this.boxes, this.dryWeightKg,
    this.reasonCode, this.notes, this.ncrId,
    this.odooSyncStatus = 'local', this.createdAt, this.voidedAt,
  });

  bool get isScrap => kind == 'scrap';
  bool get isVoided => voidedAt != null;

  factory QuarantineResolution.fromJson(Map<String, dynamic> json) =>
      QuarantineResolution(
        id: json['id'],
        docNumber: json['doc_number'],
        poId: json['po_id'],
        moRef: json['mo_ref'],
        kind: json['kind'] ?? '',
        boxes: json['boxes'] ?? 0,
        dryWeightKg: (json['dry_weight_kg'] as num?)?.toDouble(),
        reasonCode: json['reason_code'],
        notes: json['notes'],
        ncrId: json['ncr_id'],
        odooSyncStatus: json['odoo_sync_status'] ?? 'local',
        createdAt: json['created_at'] != null ? DateTime.tryParse(json['created_at']) : null,
        voidedAt: json['voided_at'] != null ? DateTime.tryParse(json['voided_at']) : null,
      );
}

class QuarantineSummary {
  final int totalQuarantineBoxes;
  final int resolvedBoxes;
  final int scrapBoxes;
  final int releasedBoxes;
  final double scrapKg;
  final int remainingBoxes;
  final List<QuarantineResolution> resolutions;

  QuarantineSummary({
    this.totalQuarantineBoxes = 0, this.resolvedBoxes = 0,
    this.scrapBoxes = 0, this.releasedBoxes = 0, this.scrapKg = 0,
    this.remainingBoxes = 0, this.resolutions = const [],
  });

  factory QuarantineSummary.fromJson(Map<String, dynamic> json) =>
      QuarantineSummary(
        totalQuarantineBoxes: json['total_quarantine_boxes'] ?? 0,
        resolvedBoxes: json['resolved_boxes'] ?? 0,
        scrapBoxes: json['scrap_boxes'] ?? 0,
        releasedBoxes: json['released_boxes'] ?? 0,
        scrapKg: (json['scrap_kg'] ?? 0).toDouble(),
        remainingBoxes: json['remaining_boxes'] ?? 0,
        resolutions: (json['resolutions'] as List<dynamic>? ?? [])
            .map((e) => QuarantineResolution.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class OrderQualityFlag {
  final int poId;
  final int openNcrCount;
  final bool criticalOpenNcr;
  final int totalNcrCount;
  final int totalQuarantineBoxes;
  final int resolvedBoxes;
  final int remainingQuarantineBoxes;
  final double scrapKg;

  OrderQualityFlag({
    required this.poId, this.openNcrCount = 0, this.criticalOpenNcr = false,
    this.totalNcrCount = 0, this.totalQuarantineBoxes = 0,
    this.resolvedBoxes = 0, this.remainingQuarantineBoxes = 0, this.scrapKg = 0,
  });

  factory OrderQualityFlag.fromJson(Map<String, dynamic> json) => OrderQualityFlag(
    poId: json['po_id'],
    openNcrCount: json['open_ncr_count'] ?? 0,
    criticalOpenNcr: json['critical_open_ncr'] ?? false,
    totalNcrCount: json['total_ncr_count'] ?? 0,
    totalQuarantineBoxes: json['total_quarantine_boxes'] ?? 0,
    resolvedBoxes: json['resolved_boxes'] ?? 0,
    remainingQuarantineBoxes: json['remaining_quarantine_boxes'] ?? 0,
    scrapKg: (json['scrap_kg'] ?? 0).toDouble(),
  );
}
