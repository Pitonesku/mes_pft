import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';
import 'operator_screen.dart';
import 'user_management.dart';
import 'machine_shift_setup.dart';
import '../auth_screen.dart';
import '../../api_service.dart';
import '../../widgets/sync_button.dart';
import 'audit_screen.dart';
import 'about_screen.dart';
import '../web/ai_analysis_screen.dart';


// --- ADMIN DASHBOARD ---
class AdminDashboard extends StatefulWidget {
  final User currentUser;
  const AdminDashboard({super.key, required this.currentUser});

  @override
  State<AdminDashboard> createState() => _AdminDashboardState();
}

class _AdminDashboardState extends State<AdminDashboard> {
  @override
  Widget build(BuildContext context) {
    bool isSuper = widget.currentUser.role == UserRole.superAdmin;

    return Scaffold(
      appBar: AppBar(
        title: Text(isSuper ? "Super Admin Panel" : "Manager Dashboard"),
        backgroundColor: isSuper ? Colors.red[800] : Colors.blue[800],
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.info_outline),
            tooltip: 'About App',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => const AboutScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: () => Navigator.pushAndRemoveUntil(
              context, 
              MaterialPageRoute(builder: (context) => const LoginScreen()), 
              (route) => false
            ),
          )
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              _buildMenuCard(
                "Fill Production Report",
                "Submit shift data as yourself",
                Icons.edit_document,
                Colors.deepPurple,
                () => Navigator.push(context, MaterialPageRoute(builder: (c) => ReportPage(operator: widget.currentUser))),
              ),
              _buildMenuCard(
                "Purchase Orders",
                "Manage POs, tech specs and targets",
                Icons.assignment,
                Colors.blue,
                () => Navigator.push(context, MaterialPageRoute(builder: (c) => const POListScreen())),
              ),
              _buildMenuCard(
                "Material Dictionary",
                "Configure types and categories of raw materials",
                Icons.inventory,
                Colors.orange,
                () => Navigator.push(context, MaterialPageRoute(builder: (c) => const MaterialListScreen())),
              ),
            if (isSuper || widget.currentUser.role == UserRole.manager)
              _buildMenuCard(
                "AI Analysis",
                "Ask AI questions about production data",
                Icons.psychology,
                Colors.teal,
                () => Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (c) => Scaffold(
                      appBar: AppBar(
                        title: const Text('AI Analysis'),
                        backgroundColor: Colors.teal,
                        foregroundColor: Colors.white,
                      ),
                      body: AiAnalysisScreen(currentUser: widget.currentUser),
                    ),
                  ),
                ),
              ),
            _buildMenuCard(
              "My Profile",
              "Security, name and recovery email",
              Icons.person,
              Colors.grey,
              () => Navigator.push(context, MaterialPageRoute(builder: (c) => ProfileScreen(user: widget.currentUser))),
            ),
            if (isSuper) ...[
              const SizedBox(height: 20),
              const Divider(),
              _buildMenuCard(
                "User Management",
                "Add/Edit users, roles and rights",
                Icons.people,
                Colors.red,
                () => Navigator.push(context, MaterialPageRoute(builder: (c) => const UserManagementScreen())),
              ),
              _buildMenuCard(
                "Machine & Shift Setup",
                "Timing and hardware configuration",
                Icons.precision_manufacturing,
                Colors.red,
                () => Navigator.push(context, MaterialPageRoute(builder: (c) => const MachineShiftSetupScreen())),
              ),
            ]
          ],
        ),
        ),
      ),
    );
  }

  Widget _buildMenuCard(String title, String sub, IconData icon, Color color, VoidCallback onTap) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        leading: Icon(icon, size: 36, color: color),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(sub),
        trailing: const Icon(Icons.arrow_forward_ios, size: 18),
        onTap: onTap,
      ),
    );
  }
}

// --- PURCHASE ORDERS LIST ---
class POListScreen extends StatefulWidget {
  const POListScreen({super.key});
  @override State<POListScreen> createState() => _POListScreenState();
}

class _POListScreenState extends State<POListScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Purchase Orders")),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: AppData.activePOs.length,
        itemBuilder: (context, index) {
          final po = AppData.activePOs[index];
          return Card(
            color: po.isHidden ? Colors.grey[200] : Colors.white,
            margin: const EdgeInsets.only(bottom: 12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(po.poNumber, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.blue)),
                      Row(children: [
                        IconButton(
                          icon: const Icon(Icons.edit, color: Colors.orange), 
                          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (c) => CreatePOPage(existingPO: po))).then((_) => setState(() {}))
                        ),
                        
                        ActionSyncButton(
                            isIcon: true,
                            color: Colors.blueGrey,
                            onSync: () async {
                              po.isHidden = !po.isHidden; 
                              bool success = await ApiService.updatePurchaseOrder(po.id!, po);
                              if (!success) po.isHidden = !po.isHidden; 
                              return success;
                            },
                            successMsg: "Visibility status changed",
                            onSuccess: () {
                              setState(() {}); 
                            },
                            child: Icon(po.isHidden ? Icons.visibility_off : Icons.visibility, size: 20),
                          ),

                        // --- Audit button for PO ---
                        IconButton(
                          icon: const Icon(Icons.bar_chart_rounded, color: Colors.blueAccent),
                          tooltip: 'PO Audit',
                          onPressed: () {
                            Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (context) => AuditPage(initialPO: po), 
                              ),
                            );
                          },
                        ),
                        // -----------------------------------

                        IconButton(
                          icon: const Icon(Icons.delete, color: Colors.red), 
                          onPressed: () => _confirmDelete(po)
                        ),
                      ]),
                    ],
                  ),
                  Text("Specs: ${po.diameter}x${po.length} PD${po.pd} CU${po.cu}", style: const TextStyle(fontWeight: FontWeight.w500)),
                  const Divider(),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _qtyItem("Target", po.targetQty, Colors.black),
                      _qtyItem("Produced", po.producedQty, Colors.green),
                      _qtyItem("Remaining", po.remainingQty, Colors.red),
                    ],
                  ),
                ],
              ),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (c) => const CreatePOPage())).then((_) => setState(() {})),
        child: const Icon(Icons.add),
      ),
    );
  }

  Widget _qtyItem(String label, int val, Color col) => Column(children: [
    Text(label, style: const TextStyle(fontSize: 10, color: Colors.grey)),
    Text(val.toString(), style: TextStyle(fontWeight: FontWeight.bold, color: col)),
  ]);

  void _confirmDelete(PurchaseOrder po) {
    showDialog(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, setD) {
      bool _saving = false;
      return AlertDialog(
      title: const Text("Delete Order?"),
      content: Text("Delete ${po.poNumber} permanently?"),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.pop(ctx),
          child: const Text("CANCEL")),
        TextButton(
          onPressed: _saving ? null : () async {
            setD(() => _saving = true);
            try {
              Navigator.pop(ctx);
              if (po.id == null) {
                // If PO does not have an ID yet, remove locally and warn the user.
                setState(() => AppData.activePOs.remove(po));
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text("Order removed locally but not synced with server."),
                  backgroundColor: Colors.orange,
                ));
                return;
              }

              bool deleted = await ApiService.deletePurchaseOrder(po.id!);
              if (deleted) {
                setState(() => AppData.activePOs.remove(po));
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text("Order deleted successfully."),
                  backgroundColor: Colors.green,
                ));
              } else {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text("Failed to delete order on server."),
                  backgroundColor: Colors.red,
                ));
              }
            } finally {
              // Dialog already popped above
            }
          },
          child: _saving
              ? const SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.red))
              : const Text("DELETE", style: TextStyle(color: Colors.red)),
        ),
      ],
    );
    }));
  }
}

// --- CREATE / EDIT PO FORM ---

// Убедитесь, что пути соответствуют вашим файлам:
// import '../../models.dart';
// import '../../api_service.dart';
// import '../app_data.dart';
// import '../../widgets/sync_button.dart'; 

class CreatePOPage extends StatefulWidget {
  final PurchaseOrder? existingPO;
  const CreatePOPage({super.key, this.existingPO});
  
  @override 
  State<CreatePOPage> createState() => _CreatePOPageState();
}

class _CreatePOPageState extends State<CreatePOPage> {
  final _formKey = GlobalKey<FormState>();
  late TextEditingController _poNum, _qty, _box, _dia, _len, _pd, _cu, _weight;
  String? _acetate, _paper, _pva, _hm, _tri;

  @override
  void initState() {
    super.initState();
    final p = widget.existingPO;
    _poNum = TextEditingController(text: p?.poNumber ?? "");
    _qty = TextEditingController(text: p != null ? _formatKpcs(p.targetQty) : "");
    _box = TextEditingController(text: p?.boxType.toString() ?? "");
    _dia = TextEditingController(text: p?.diameter.toString() ?? "");
    _len = TextEditingController(text: p?.length.toString() ?? "");
    _pd = TextEditingController(text: p?.pd.toString() ?? "");
    _cu = TextEditingController(text: p?.cu.toString() ?? "");
    _weight = TextEditingController(text: p?.weight.toString() ?? "");
    
    _acetate = p?.acetateType; 
    _paper = p?.paperType; 
    _pva = p?.pvaGlueType; 
    _hm = p?.hmGlueType; 
    _tri = p?.triacetinType;
  }

  // Format targetQty (stored as pcs) back to k pcs display, e.g. 5000 -> "5", 5500 -> "5.5"
  String _formatKpcs(int qty) {
    final double kpcs = qty / 1000.0;
    if (kpcs == kpcs.truncateToDouble()) {
      return kpcs.toInt().toString();
    }
    return kpcs.toStringAsFixed(1);
  }

  // Умная функция, которая меняет запятую на точку
  double _parseNum(String text) {
    if (text.trim().isEmpty) return 0.0;
    return double.tryParse(text.replaceAll(',', '.')) ?? 0.0;
  }

  // Локальный валидатор для чисел
  String? _numberValidator(String? value) {
    if (value == null || value.trim().isEmpty) return 'Required';
    if (double.tryParse(value.replaceAll(',', '.')) == null) return 'Invalid number';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    // Временная переменная, чтобы передать созданный PO из onSync в onSuccess
    PurchaseOrder? pendingPO;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.existingPO == null ? "New PO" : "Edit PO"),
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _buildSection("General", [
              TextFormField(
                controller: _poNum, 
                decoration: const InputDecoration(labelText: "PO Number *"),
                validator: (v) => v == null || v.trim().isEmpty ? 'Required' : null,
              ),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: TextFormField(
                  controller: _qty, 
                  decoration: const InputDecoration(labelText: "Target (k pcs) *"), 
                  keyboardType: TextInputType.number,
                  validator: _numberValidator,
                )),
                const SizedBox(width: 10),
                Expanded(child: TextFormField(
                  controller: _box, 
                  decoration: const InputDecoration(labelText: "Box Type *"), 
                  keyboardType: TextInputType.number,
                  validator: _numberValidator,
                )),
              ]),
            ]),
            
            _buildSection("Tech Specs", [
              Row(children: [
                Expanded(child: TextFormField(
                  controller: _dia, decoration: const InputDecoration(labelText: "Diameter *"),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: _numberValidator,
                )),
                const SizedBox(width: 10),
                Expanded(child: TextFormField(
                  controller: _len, decoration: const InputDecoration(labelText: "Length *"),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: _numberValidator,
                )),
                const SizedBox(width: 10),
                Expanded(child: TextFormField(
                  controller: _pd, decoration: const InputDecoration(labelText: "PD *"),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: _numberValidator,
                )),
              ]),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: TextFormField(
                  controller: _cu, decoration: const InputDecoration(labelText: "CU (Porosity) *"),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: _numberValidator,
                )),
                const SizedBox(width: 10),
                Expanded(child: TextFormField(
                  controller: _weight, decoration: const InputDecoration(labelText: "Weight (mg) *"),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: _numberValidator,
                )),
              ]),
            ]),
            
            _buildSection("Materials", [
              _matDrop("Acetate *", MaterialCategory.acetate, _acetate, (v) => setState(() => _acetate = v)),
              _matDrop("Paper *", MaterialCategory.paper, _paper, (v) => setState(() => _paper = v)),
              _matDrop("PVA (Cold Glue) *", MaterialCategory.coldGlue, _pva, (v) => setState(() => _pva = v)),
              _matDrop("Hot Melt Glue *", MaterialCategory.hotMelt, _hm, (v) => setState(() => _hm = v)),
              _matDrop("Triacetin *", MaterialCategory.triacetin, _tri, (v) => setState(() => _tri = v)),
            ]),
            const SizedBox(height: 24),

            // --- УМНАЯ КНОПКА СОХРАНЕНИЯ ---
            ActionSyncButton(
              color: Colors.blue,
              successMsg: widget.existingPO == null ? "PO created successfully" : "PO updated successfully",
              errorMsg: "Error: Please check form fields or server connection",
              
              onSync: () async {
                // 1. Проверяем валидацию формы (красные подчеркивания)
                if (!_formKey.currentState!.validate()) return false;

                // 2. Создаем объект (используем _parseNum для защиты от запятых)
                pendingPO = PurchaseOrder(
                  id: widget.existingPO?.id, // ВАЖНО для обновления
                  poNumber: _poNum.text.trim(),
                  createdAt: widget.existingPO?.createdAt ?? DateTime.now(),
                  diameter: _parseNum(_dia.text),
                  length: _parseNum(_len.text),
                  pd: _parseNum(_pd.text),
                  weight: _parseNum(_weight.text),
                  cu: int.tryParse(_cu.text) ?? 0,
                  boxType: int.tryParse(_box.text) ?? 0,
                  targetQty: ((double.tryParse(_qty.text.replaceAll(',', '.')) ?? 0) * 1000).round(),
                  acetateType: _acetate ?? "",
                  paperType: _paper ?? "",
                  pvaGlueType: _pva ?? "",
                  hmGlueType: _hm ?? "",
                  triacetinType: _tri ?? "",
                  producedQty: widget.existingPO?.producedQty ?? 0,
                  isHidden: widget.existingPO?.isHidden ?? false,
                );

                // 3. Отправляем нужный запрос
                if (widget.existingPO == null) {
                  final created = await ApiService.addPurchaseOrder(pendingPO!);
                  if (created == null) return false;
                  pendingPO = created;
                  return true;
                } else {
                  return await ApiService.updatePurchaseOrder(widget.existingPO!.id!, pendingPO!);
                }
              },
              
              onSuccess: () {
                if (pendingPO == null) return;
                
                setState(() {
                  if (widget.existingPO != null) {
                    // Ищем старый заказ по ID и заменяем его новым
                    int idx = AppData.activePOs.indexWhere((p) => p.id == widget.existingPO!.id);
                    if (idx != -1) {
                      AppData.activePOs[idx] = pendingPO!;
                    }
                  } else {
                    AppData.activePOs.add(pendingPO!);
                  }
                });
                
                Navigator.pop(context);
              },
              child: const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text("SAVE ORDER", style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
            
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  // Вспомогательный метод для секций
  Widget _buildSection(String title, List<Widget> items) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 8), 
        child: Text(title, style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.blue))
      ),
      Card(
        elevation: 2,
        child: Padding(
          padding: const EdgeInsets.all(16), 
          child: Column(children: items)
        )
      ),
    ],
  );

  // Вспомогательный метод для выпадающих списков материалов
  Widget _matDrop(String label, MaterialCategory category, String? currentValue, ValueChanged<String?> onChanged) {
    // Берем только нескрытые материалы нужной категории
    final items = AppData.materialDictionary.where((m) => m.category == category && !m.isHidden).toList();
    
    // Если текущее значение было скрыто/удалено, сбрасываем его
    if (currentValue != null && !items.any((m) => m.type == currentValue)) {
      currentValue = null;
    }

    return DropdownButtonFormField<String>(
      decoration: InputDecoration(labelText: label),
      initialValue: currentValue,
      items: items.map((m) => DropdownMenuItem(value: m.type, child: Text(m.type))).toList(),
      onChanged: onChanged,
      validator: (v) => v == null || v.isEmpty ? 'Required' : null,
    );
  }
}




// --- СЛОВАРЬ МАТЕРИАЛОВ ---
class MaterialListScreen extends StatefulWidget {
  const MaterialListScreen({super.key});
  @override State<MaterialListScreen> createState() => _MaterialListScreenState();
}

class _MaterialListScreenState extends State<MaterialListScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Material Dictionary"), backgroundColor: Colors.orange[800], foregroundColor: Colors.white),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: MaterialCategory.values.map((cat) {
          final items = AppData.materialDictionary.where((m) => m.category == cat).toList();
          if (items.isEmpty) return const SizedBox();
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 16, bottom: 8), child: Text(cat.name.toUpperCase(), style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.orange))),
            ...items.map((mat) => Card(
              color: mat.isHidden ? Colors.grey[200] : Colors.white,
              child: ListTile(
                title: Text(mat.type, style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text("Batch: ${mat.batch ?? 'N/A'}"),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(icon: const Icon(Icons.edit, size: 20), onPressed: () => _editMaterial(mat)),
                  IconButton(icon: Icon(mat.isHidden ? Icons.visibility_off : Icons.visibility), onPressed: () => setState(() => mat.isHidden = !mat.isHidden)),
                  ActionSyncButton(
                    isIcon: true, // Говорим кнопке, что она должна выглядеть как иконка
                    color: Colors.red,
                    
                    // 1. Confirmation dialog settings
                    confirmTitle: "Delete material?",
                    confirmText: "Are you sure you want to permanently delete '${mat.type}'?",
                    
                    // 2. Логика запроса к серверу (encoding is handled inside deleteMaterial)
                    onSync: () => ApiService.deleteMaterial(mat.type),
                    
                    // 3. Логика обновления экрана при успехе
                    successMsg: "Material deleted",
                    onSuccess: () {
                      setState(() {
                        AppData.materialDictionary.remove(mat);
                      });
                    },
                    child: const Icon(Icons.delete, size: 20),
)
                ]),
              ),
            )),
          ]);
        }).toList(),
      ),
      floatingActionButton: FloatingActionButton(onPressed: () => _editMaterial(null), backgroundColor: Colors.orange[800], child: const Icon(Icons.add)),
    );
  }

 

  void _editMaterial(RawMaterial? mat) {
    final typeC = TextEditingController(text: mat?.type ?? "");
    final batchC = TextEditingController(text: mat?.batch ?? "");
    MaterialCategory cat = mat?.category ?? MaterialCategory.acetate;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setS) => AlertDialog(
          title: Text(mat == null ? "Add Material" : "Edit Material"),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<MaterialCategory>(
                initialValue: cat,
                items: MaterialCategory.values.map((c) => DropdownMenuItem(value: c, child: Text(c.name))).toList(),
                onChanged: (v) => setS(() => cat = v!),
              ),
              TextField(controller: typeC, decoration: const InputDecoration(labelText: "Type Name")),
              TextField(controller: batchC, decoration: const InputDecoration(labelText: "Batch #")),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("CANCEL")),
            
            // --- УМНАЯ КНОПКА СОХРАНЕНИЯ ---
            ActionSyncButton(
              color: Colors.green,
              successMsg: "Material saved successfully",
              errorMsg: "Save failed! Check network or empty name.",
              
              onSync: () async {
                final name = typeC.text.trim();
                if (name.isEmpty) return false;

                final newMat = RawMaterial(
                  category: cat,
                  type: name,
                  batch: batchC.text.trim(),
                  isHidden: mat?.isHidden ?? false,
                );

                // ТА САМАЯ РАЗВИЛКА:
                if (mat == null) {
                  // Если создаем новый
                  return await ApiService.addMaterial(newMat);
                } else {
                  // Если редактируем старый (отправляем PUT запрос)
                  return await ApiService.updateMaterial(mat.type, newMat);
                }
              },
              
              onSuccess: () {
                setState(() {
                  if (mat == null) {
                    // Добавляем в локальный список
                    AppData.materialDictionary.add(
                      RawMaterial(category: cat, type: typeC.text.trim(), batch: batchC.text.trim())
                    );
                  } else {
                    // Обновляем существующий объект в памяти
                    mat.category = cat;
                    mat.type = typeC.text.trim();
                    mat.batch = batchC.text.trim();
                  }
                });
                Navigator.pop(ctx); // Закрываем окно
              },
              child: const Text("SAVE", style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }
}

// --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---
class ProfileScreen extends StatefulWidget {
  final User user;
  const ProfileScreen({super.key, required this.user});
  @override State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late TextEditingController _name, _email, _pass;
  bool _saving = false;
  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.user.name);
    _email = TextEditingController(text: widget.user.email);
    _pass = TextEditingController(text: widget.user.password);
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("My Profile")),
      body: ListView(padding: const EdgeInsets.all(24), children: [
        TextField(controller: _name, decoration: const InputDecoration(labelText: "Username")),
        const SizedBox(height: 16),
        TextField(controller: _email, decoration: const InputDecoration(labelText: "Recovery Email")),
        const SizedBox(height: 16),
        TextField(controller: _pass, decoration: const InputDecoration(labelText: "Password"), obscureText: true),
        const SizedBox(height: 32),
        ElevatedButton(
          onPressed: _saving ? null : () async {
            setState(() => _saving = true);
            try {
              setState(() { widget.user.name = _name.text; widget.user.email = _email.text; widget.user.password = _pass.text; });
              await ApiService.updateUser(widget.user);
              if (mounted) Navigator.pop(context);
            } finally {
              if (mounted) setState(() => _saving = false);
            }
          },
          child: _saving
              ? const SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text("SAVE CHANGES")),
      ]),
    );
  }
}