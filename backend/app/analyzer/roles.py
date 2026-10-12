"""Android role classification from supertypes, annotations and naming."""
from __future__ import annotations

from .resolver import SymbolIndex, TypeInfo

EXTERNAL_SUPER_ROLES = {
    "activity": {"Activity", "AppCompatActivity", "FragmentActivity", "ComponentActivity",
                 "ListActivity", "FlutterActivity"},
    "fragment": {"Fragment", "DialogFragment", "BottomSheetDialogFragment",
                 "PreferenceFragmentCompat", "ListFragment"},
    "service": {"Service", "IntentService", "LifecycleService", "JobService", "JobIntentService",
                "AccessibilityService", "MediaBrowserServiceCompat", "FirebaseMessagingService"},
    "receiver": {"BroadcastReceiver", "AppWidgetProvider"},
    "viewmodel": {"ViewModel", "AndroidViewModel"},
    "worker": {"Worker", "CoroutineWorker", "ListenableWorker", "RxWorker"},
}
ANNOTATION_ROLES = {
    "Dao": "dao", "HiltViewModel": "viewmodel", "Repository": "repository",
}


def classify(info: TypeInfo, index: SymbolIndex) -> tuple[list[str], dict[str, str]]:
    roles: dict[str, str] = {}
    for t in index.hierarchy(info):
        prefix = "" if t is info else f"{t.decl.name} -> "
        for s in t.supers:
            if s.res.info is not None:
                continue
            simple = (s.res.fqn or s.name).rsplit(".", 1)[-1]
            for role, names in EXTERNAL_SUPER_ROLES.items():
                if simple in names and role not in roles:
                    how = "extends" if s.ctor_call or t.decl.kind == "class" else "implements"
                    roles[role] = f"{prefix}{how} {s.res.fqn or s.name}"
        for ann in t.decl.annotations:
            role = ANNOTATION_ROLES.get(ann.rsplit(".", 1)[-1])
            if role and role not in roles:
                roles[role] = f"annotated @{ann}"
    name = info.decl.name
    if "repository" not in roles and info.decl.kind != "annotation" and (
            name.endswith("Repository") or name.endswith("RepositoryImpl")):
        roles["repository"] = "naming convention (*Repository)"
    return list(roles), roles
