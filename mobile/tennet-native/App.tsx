import { BarcodeScanningResult, CameraView, useCameraPermissions } from "expo-camera";
import * as DocumentPicker from "expo-document-picker";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { LinearGradient } from "expo-linear-gradient";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { StatusBar as ExpoStatusBar } from "expo-status-bar";
import React, { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  StatusBar as NativeStatusBar,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  API_BASE_URL,
  DashboardSummary,
  EvidencePrintTicket,
  EvidenceTask,
  EvidenceTasksResponse,
  PublicEvidenceUploadLink,
  RecoveryAction,
  RecoveryActionsResponse,
  RecoverySummary,
  Session,
  UploadableFile,
  WEB_APP_URL,
  clearSession,
  loadSession,
  login,
  request,
  uploadFile,
} from "./src/api";
import { getNativePrinterCapabilities, hasNativePrinter, printTicketOnNativePrinter } from "./src/nativePrinter";
import { colors, radius, shadow, spacing } from "./src/theme";
import { colorForStatus, formatCurrency, formatDate, getUploadTokenFromUrl, labelForEvidence, priorityRank, readableLabel } from "./src/utils";

type TabKey = "home" | "proofs" | "scan" | "recovery" | "account";

type AppData = {
  dashboard: DashboardSummary | null;
  tasks: EvidenceTask[];
  nextActions: RecoveryAction[];
  recovery: RecoverySummary | null;
};

const initialData: AppData = {
  dashboard: null,
  tasks: [],
  nextActions: [],
  recovery: null,
};

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<TabKey>("home");
  const [data, setData] = useState<AppData>(initialData);
  const [selectedTask, setSelectedTask] = useState<EvidenceTask | null>(null);
  const [publicToken, setPublicToken] = useState<string | null>(null);
  const [publicLink, setPublicLink] = useState<PublicEvidenceUploadLink | null>(null);
  const isFieldOnly = session?.user.role === "staff";

  const refresh = useCallback(async () => {
    if (!session) {
      return;
    }
    setLoading(true);
    try {
      const [dashboard, tasks, recovery, recoveryActions] = await Promise.all([
        request<DashboardSummary>("/v1/dashboard/summary", {}, session),
        request<EvidenceTasksResponse>("/v1/evidence-tasks?status=pending&limit=50", {}, session),
        request<RecoverySummary>("/v1/recovery/summary", {}, session),
        request<RecoveryActionsResponse>("/v1/recovery/actions?limit=50", {}, session),
      ]);
      setData({
        dashboard,
        tasks: tasks.tasks.sort((left, right) => priorityRank(left.priority) - priorityRank(right.priority)),
        recovery,
        nextActions: recoveryActions.actions.sort((left, right) => priorityRank(left.priority) - priorityRank(right.priority)),
      });
    } catch (error) {
      Alert.alert("TENNET", error instanceof Error ? error.message : "Impossible de charger les donnees.");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    loadSession()
      .then((stored) => setSession(stored))
      .finally(() => setBooting(false));
  }, []);

  useEffect(() => {
    if (session) {
      void refresh();
    }
  }, [refresh, session]);

  const handleLogout = async () => {
    await clearSession();
    setSession(null);
    setData(initialData);
    setSelectedTask(null);
    setPublicToken(null);
    setPublicLink(null);
    setTab("home");
  };

  const handleToken = async (rawValue: string) => {
    const token = getUploadTokenFromUrl(rawValue);
    if (!token) {
      Alert.alert("QR non reconnu", "Ce code ne correspond pas a un lien preuve TENNET.");
      return;
    }
    setPublicToken(token);
    setTab("scan");
    try {
      const link = await request<PublicEvidenceUploadLink>(`/v1/evidence-upload-links/${encodeURIComponent(token)}`, {}, null);
      setPublicLink(link);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (error) {
      setPublicToken(null);
      Alert.alert("Lien invalide", error instanceof Error ? error.message : "Ce lien preuve n'est plus disponible.");
    }
  };

  if (booting) {
    return (
      <Shell>
        <LoadingState title="Chargement TENNET" />
      </Shell>
    );
  }

  if (!session) {
    return (
      <Shell>
        <LoginScreen onLoggedIn={setSession} />
      </Shell>
    );
  }

  return (
    <Shell>
      <View style={styles.app}>
        <Header session={session} loading={loading} onRefresh={refresh} />
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor={colors.primary} />}
        >
          {tab === "home" ? (
            isFieldOnly ? (
              <ProofsScreen tasks={data.tasks} selectedTask={selectedTask} onOpenTask={setSelectedTask} onUploaded={refresh} session={session} minimal />
            ) : (
              <HomeScreen data={data} onOpenTask={setSelectedTask} onGoProofs={() => setTab("proofs")} onGoRecovery={() => setTab("recovery")} />
            )
          ) : null}
          {tab === "proofs" ? (
            <ProofsScreen tasks={data.tasks} selectedTask={selectedTask} onOpenTask={setSelectedTask} onUploaded={refresh} session={session} />
          ) : null}
          {tab === "scan" ? (
            <ScanScreen token={publicToken} link={publicLink} onToken={handleToken} onUploaded={refresh} />
          ) : null}
          {tab === "recovery" ? <RecoveryScreen summary={data.recovery} actions={data.nextActions} /> : null}
          {tab === "account" ? <AccountScreen session={session} onLogout={handleLogout} /> : null}
        </ScrollView>
        {isFieldOnly ? null : <BottomNav active={tab} onChange={setTab} />}
      </View>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <ExpoStatusBar style="dark" />
      {children}
    </SafeAreaView>
  );
}

function LoginScreen({ onLoggedIn }: { onLoggedIn: (session: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!email || !password) {
      Alert.alert("Connexion", "Renseigne l'email et le mot de passe TENNET.");
      return;
    }
    setSubmitting(true);
    try {
      const session = await login(email, password);
      onLoggedIn(session);
    } catch (error) {
      Alert.alert("Connexion impossible", error instanceof Error ? error.message : "Verifie les identifiants TENNET.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <LinearGradient colors={["#FDF9F1", "#EAF4EF"]} style={styles.login}>
      <View style={styles.logoMark}>
        <Text style={styles.logoText}>T</Text>
      </View>
      <Text style={styles.loginTitle}>TENNET</Text>
      <Text style={styles.loginSubtitle}>Recuperation Uber, preuves terrain et suivi des paiements dans une app native.</Text>
      <View style={styles.formCard}>
        <Text style={styles.fieldLabel}>Email</Text>
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          autoComplete="email"
          style={styles.input}
          placeholder="owner@exemple.com"
          placeholderTextColor={colors.gray}
        />
        <Text style={styles.fieldLabel}>Mot de passe</Text>
        <TextInput
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="password"
          style={styles.input}
          placeholder="Mot de passe TENNET"
          placeholderTextColor={colors.gray}
        />
        <PrimaryButton label={submitting ? "Connexion..." : "Se connecter"} onPress={submit} disabled={submitting} />
      </View>
      <Text style={styles.securityNote}>Le token est stocke dans le coffre securise de l'appareil. Aucun mot de passe Gmail n'est demande.</Text>
    </LinearGradient>
  );
}

function Header({ session, loading, onRefresh }: { session: Session; loading: boolean; onRefresh: () => void }) {
  return (
    <View style={styles.header}>
      <View style={styles.headerIdentity}>
        <Text style={styles.headerEyebrow} numberOfLines={1}>TENNET mobile</Text>
        <Text style={styles.headerTitle} numberOfLines={1}>Bonjour {session.user.full_name || session.user.email.split("@")[0]}</Text>
      </View>
      <Pressable style={styles.refreshButton} onPress={onRefresh} disabled={loading}>
        <Text style={styles.refreshButtonText}>{loading ? "..." : "Sync"}</Text>
      </Pressable>
    </View>
  );
}

function HomeScreen({
  data,
  onOpenTask,
  onGoProofs,
  onGoRecovery,
}: {
  data: AppData;
  onOpenTask: (task: EvidenceTask) => void;
  onGoProofs: () => void;
  onGoRecovery: () => void;
}) {
  const urgentTasks = data.tasks.filter((task) => task.priority === "urgent" || task.priority === "high").slice(0, 3);
  return (
    <View style={styles.stack}>
      <HeroCard dashboard={data.dashboard} />
      <View style={styles.quickGrid}>
        <QuickAction label="Preuves a fournir" value={String(data.tasks.length)} onPress={onGoProofs} />
        <QuickAction
          label="Montant contestable"
          value={formatCurrency(data.recovery?.totals.claimable_amount ?? 0)}
          onPress={onGoRecovery}
        />
      </View>
      <SectionHeader title="A faire maintenant" action="Toutes les preuves" onPress={onGoProofs} />
      {urgentTasks.length ? (
        urgentTasks.map((task) => <EvidenceTaskCard key={task.id} task={task} onPress={() => onOpenTask(task)} />)
      ) : (
        <EmptyState title="Aucune preuve urgente" body="Les prochaines actions apparaitront ici apres import ou reconciliation." />
      )}
      <SectionHeader title="Actions recovery" action="Cockpit" onPress={onGoRecovery} />
      {data.nextActions.slice(0, 4).map((action) => (
        <RecoveryActionCard key={`${action.case_type}-${action.case_id}-${action.action_type}`} action={action} />
      ))}
    </View>
  );
}

function HeroCard({ dashboard }: { dashboard: DashboardSummary | null }) {
  return (
    <LinearGradient colors={[colors.primaryDark, colors.primary]} style={styles.hero}>
      <Text style={styles.heroKicker}>Cockpit terrain</Text>
      <Text style={styles.heroTitle}>Ne laisse aucune perte detectee sans revue.</Text>
      <View style={styles.heroMetrics}>
        <Metric label="A recuperer" value={formatCurrency(dashboard?.total_pending_amount ?? 0)} light />
        <Metric label="Recupere" value={formatCurrency(dashboard?.total_recovered_amount ?? 0)} light />
      </View>
    </LinearGradient>
  );
}

function ProofsScreen({
  tasks,
  selectedTask,
  onOpenTask,
  onUploaded,
  session,
  minimal = false,
}: {
  tasks: EvidenceTask[];
  selectedTask: EvidenceTask | null;
  onOpenTask: (task: EvidenceTask | null) => void;
  onUploaded: () => Promise<void>;
  session: Session;
  minimal?: boolean;
}) {
  const task = selectedTask ?? tasks[0] ?? null;
  return (
    <View style={styles.stack}>
      <Text style={styles.screenTitle}>{minimal ? "A faire maintenant" : "Preuves terrain"}</Text>
      <Text style={styles.screenSubtitle}>
        {minimal ? "TENNET choisit la prochaine preuve. Tu imprimes, tu prends la photo, TENNET classe." : "Photographie, importe ou imprime un ticket preuve pour guider le restaurant."}
      </Text>
      {task ? <TaskDetail task={task} onUploaded={onUploaded} session={session} minimal={minimal} /> : <EmptyState title="Aucune preuve en attente" body="Tout est propre pour l'instant." />}
      {minimal ? null : (
        <>
          <SectionHeader title="File de preuves" />
          {tasks.map((item) => (
            <EvidenceTaskCard key={item.id} task={item} selected={task?.id === item.id} onPress={() => onOpenTask(item)} />
          ))}
        </>
      )}
    </View>
  );
}

function TaskDetail({ task, onUploaded, session, minimal = false }: { task: EvidenceTask; onUploaded: () => Promise<void>; session: Session; minimal?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);

  const upload = async (file: UploadableFile) => {
    setBusy("upload");
    try {
      await uploadFile(`/v1/evidence-tasks/${task.id}/upload`, file, session);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert("Preuve ajoutee", "TENNET a attache la preuve et relance la validation du dossier.");
      await onUploaded();
    } catch (error) {
      Alert.alert("Upload impossible", error instanceof Error ? error.message : "La preuve n'a pas ete envoyee.");
    } finally {
      setBusy(null);
    }
  };

  const takePhoto = async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert("Camera requise", "Autorise la camera pour photographier les preuves.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: "images", quality: 0.78 });
    if (!result.canceled && result.assets[0]) {
      await upload(assetToFile(result.assets[0], `preuve-${task.id}.jpg`, "image/jpeg"));
    }
  };

  const pickFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "application/pdf"],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (!result.canceled && result.assets[0]) {
      const asset = result.assets[0];
      await upload({
        uri: asset.uri,
        name: asset.name || `preuve-${task.id}`,
        type: asset.mimeType || "application/octet-stream",
      });
    }
  };

  const printTicket = async () => {
    setBusy("print");
    try {
      const ticket = await request<EvidencePrintTicket>(
        `/v1/evidence-tasks/${task.id}/print-ticket`,
        {
          method: "POST",
          body: JSON.stringify({ max_uses: 1, expires_in_hours: 72 }),
        },
        session,
      );
      if (hasNativePrinter()) {
        await printTicketOnNativePrinter(ticket);
        await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        await takePhoto();
      } else {
        await Print.printAsync({ html: ticket.print_html });
      }
    } catch (error) {
      Alert.alert("Impression impossible", error instanceof Error ? error.message : "Le ticket n'a pas pu etre cree.");
    } finally {
      setBusy(null);
    }
  };

  const checkPrinter = async () => {
    try {
      const capabilities = await getNativePrinterCapabilities();
      if (!capabilities.nativeModuleAvailable) {
        Alert.alert("Imprimante native", "Ce build utilise l'impression systeme. Le build Android terrain active le Bluetooth ticket.");
        return;
      }
      Alert.alert(
        "Imprimante native",
        capabilities.bluetoothEnabled ? "Bluetooth pret. TENNET imprimera sur l'imprimante ticket appairee." : "Bluetooth indisponible ou eteint sur cet appareil.",
      );
    } catch (error) {
      Alert.alert("Imprimante native", error instanceof Error ? error.message : "Verification impossible.");
    }
  };

  const shareTicket = async () => {
    setBusy("share");
    try {
      const ticket = await request<EvidencePrintTicket>(
        `/v1/evidence-tasks/${task.id}/print-ticket`,
        {
          method: "POST",
          body: JSON.stringify({ max_uses: 1, expires_in_hours: 72 }),
        },
        session,
      );
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(ticket.upload_url);
      } else {
        await Linking.openURL(ticket.upload_url);
      }
    } catch (error) {
      Alert.alert("Partage impossible", error instanceof Error ? error.message : "Le lien n'a pas pu etre partage.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.detailCard}>
      <View style={styles.cardTopLine}>
        <Badge label={readableLabel(task.priority)} tone={colorForStatus(task.priority)} />
        <Badge label={readableLabel(task.status)} tone={colorForStatus(task.status)} />
      </View>
      <Text style={styles.detailTitle}>{task.title}</Text>
      <Text style={styles.detailMeta}>{task.restaurant_name}</Text>
      <Text style={styles.detailMeta}>Commande {task.uber_order_number}</Text>
      <Text style={styles.detailProof}>{labelForEvidence(task.required_evidence_type)}</Text>
      <Text style={styles.detailBody}>{task.description || task.reason}</Text>
      <View style={styles.actionRow}>
        <PrimaryButton label={busy === "print" ? "Impression..." : "Imprimer et prendre photo"} onPress={printTicket} disabled={Boolean(busy)} />
      </View>
      {minimal ? null : (
        <>
          <View style={styles.actionRow}>
            <SecondaryButton label={busy === "upload" ? "Envoi..." : "Photo seule"} onPress={takePhoto} disabled={Boolean(busy)} />
            <SecondaryButton label="Fichier" onPress={pickFile} disabled={Boolean(busy)} />
          </View>
          <View style={styles.actionRow}>
            <SecondaryButton label="Tester imprimante" onPress={checkPrinter} disabled={Boolean(busy)} />
            <SecondaryButton label="Lien secours" onPress={shareTicket} disabled={Boolean(busy)} />
          </View>
        </>
      )}
    </View>
  );
}

function ScanScreen({
  token,
  link,
  onToken,
  onUploaded,
}: {
  token: string | null;
  link: PublicEvidenceUploadLink | null;
  onToken: (token: string) => Promise<void>;
  onUploaded: () => Promise<void>;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);
  const [manualToken, setManualToken] = useState(token ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (token) {
      setManualToken(token);
    }
  }, [token]);

  const handleScan = async (result: BarcodeScanningResult) => {
    if (scanned) {
      return;
    }
    setScanned(true);
    await onToken(result.data);
  };

  const uploadPublic = async () => {
    if (!token) {
      Alert.alert("Lien requis", "Scanne ou colle un lien preuve TENNET.");
      return;
    }
    const permissionResult = await ImagePicker.requestCameraPermissionsAsync();
    if (!permissionResult.granted) {
      Alert.alert("Camera requise", "Autorise la camera pour prendre la preuve.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: "images", quality: 0.78 });
    if (result.canceled || !result.assets[0]) {
      return;
    }
    setBusy(true);
    try {
      await uploadFile(`/v1/evidence-upload-links/${encodeURIComponent(token)}/upload`, assetToFile(result.assets[0], "preuve-ticket.jpg", "image/jpeg"), null);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert("Preuve envoyee", "La tache TENNET est completee.");
      await onUploaded();
    } catch (error) {
      Alert.alert("Upload impossible", error instanceof Error ? error.message : "La preuve n'a pas ete envoyee.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.stack}>
      <Text style={styles.screenTitle}>Scanner ticket preuve</Text>
      <Text style={styles.screenSubtitle}>Scanne le QR code imprime, puis photographie le ticket avec la preuve demandee.</Text>
      <View style={styles.scannerCard}>
        {permission?.granted ? (
          <CameraView
            style={styles.camera}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={scanned ? undefined : handleScan}
          />
        ) : (
          <View style={styles.cameraFallback}>
            <Text style={styles.emptyTitle}>Camera non autorisee</Text>
            <PrimaryButton label="Autoriser camera" onPress={requestPermission} />
          </View>
        )}
      </View>
      <View style={styles.formCard}>
        <Text style={styles.fieldLabel}>Lien ou token preuve</Text>
        <TextInput value={manualToken} onChangeText={setManualToken} style={styles.input} autoCapitalize="none" placeholder="https://app.thetennet.com/evidence-upload/..." />
        <PrimaryButton label="Verifier lien" onPress={() => onToken(manualToken)} />
      </View>
      {link ? (
        <View style={styles.detailCard}>
          <Badge label={readableLabel(link.priority)} tone={colorForStatus(link.priority)} />
          <Text style={styles.detailTitle}>{link.title}</Text>
          <Text style={styles.detailMeta}>{link.restaurant_name}</Text>
          <Text style={styles.detailMeta}>Commande {link.uber_order_number}</Text>
          <Text style={styles.detailProof}>{labelForEvidence(link.required_evidence_type)}</Text>
          <PrimaryButton label={busy ? "Envoi..." : "Photographier et envoyer"} onPress={uploadPublic} disabled={busy} />
        </View>
      ) : null}
      {scanned ? <SecondaryButton label="Scanner un autre QR" onPress={() => setScanned(false)} /> : null}
    </View>
  );
}

function RecoveryScreen({ summary, actions }: { summary: RecoverySummary | null; actions: RecoveryAction[] }) {
  return (
    <View style={styles.stack}>
      <Text style={styles.screenTitle}>Cockpit recuperation</Text>
      <Text style={styles.screenSubtitle}>Vue native des montants a traiter, preuves bloquees et actions prioritaires.</Text>
      <View style={styles.metricGrid}>
        <Metric label="Detecte" value={formatCurrency(summary?.totals.detected_amount ?? 0)} />
        <Metric label="Contestable" value={formatCurrency(summary?.totals.claimable_amount ?? 0)} />
        <Metric label="Preuves manquantes" value={formatCurrency(summary?.totals.missing_evidence_amount ?? 0)} />
        <Metric label="Recupere" value={formatCurrency(summary?.totals.recovered_amount ?? 0)} />
      </View>
      <SectionHeader title="Actions operationnelles" />
      {actions.length ? (
        actions.map((action) => <RecoveryActionCard key={`${action.case_type}-${action.case_id}-${action.action_type}`} action={action} />)
      ) : (
        <EmptyState title="Aucune action" body="Le cockpit est a jour." />
      )}
    </View>
  );
}

function AccountScreen({ session, onLogout }: { session: Session; onLogout: () => void }) {
  return (
    <View style={styles.stack}>
      <Text style={styles.screenTitle}>Compte</Text>
      <View style={styles.detailCard}>
        <Text style={styles.detailTitle}>{session.user.full_name || session.user.email}</Text>
        <Text style={styles.detailMeta}>{session.user.email}</Text>
        <Badge label={readableLabel(session.user.role)} tone={colors.primary} />
      </View>
      <View style={styles.detailCard}>
        <Text style={styles.detailTitle}>Environnement</Text>
        <Text style={styles.detailMeta}>API: {API_BASE_URL}</Text>
        <Text style={styles.detailMeta}>Web: {WEB_APP_URL}</Text>
        <View style={styles.actionRow}>
          <SecondaryButton label="Ouvrir TENNET web" onPress={() => Linking.openURL(WEB_APP_URL)} />
          <SecondaryButton label="Support API" onPress={() => Linking.openURL(`${API_BASE_URL}/health`)} />
        </View>
      </View>
      <PrimaryButton label="Se deconnecter" onPress={onLogout} danger />
    </View>
  );
}

function BottomNav({ active, onChange }: { active: TabKey; onChange: (tab: TabKey) => void }) {
  const tabs: { key: TabKey; label: string }[] = [
    { key: "home", label: "Accueil" },
    { key: "proofs", label: "Preuves" },
    { key: "scan", label: "Scan" },
    { key: "recovery", label: "Recovery" },
    { key: "account", label: "Compte" },
  ];
  return (
    <View style={styles.bottomNav}>
      {tabs.map((item) => (
        <Pressable key={item.key} style={[styles.navItem, active === item.key && styles.navItemActive]} onPress={() => onChange(item.key)}>
          <Text style={[styles.navText, active === item.key && styles.navTextActive]}>{item.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function EvidenceTaskCard({ task, selected, onPress }: { task: EvidenceTask; selected?: boolean; onPress: () => void }) {
  return (
    <Pressable style={[styles.listCard, selected && styles.listCardSelected]} onPress={onPress}>
      <View style={styles.cardTopLine}>
        <Badge label={readableLabel(task.priority)} tone={colorForStatus(task.priority)} />
        <Text style={styles.amountText}>{formatCurrency(task.order_amount ?? 0, task.currency)}</Text>
      </View>
      <Text style={styles.cardTitle}>{labelForEvidence(task.required_evidence_type)}</Text>
      <Text style={styles.cardMeta}>{task.restaurant_name}</Text>
      <Text style={styles.cardMeta}>Commande {task.uber_order_number} - {formatDate(task.due_at)}</Text>
    </Pressable>
  );
}

function RecoveryActionCard({ action }: { action: RecoveryAction }) {
  return (
    <Pressable style={styles.listCard} onPress={() => Linking.openURL(`${WEB_APP_URL}${action.url}`)}>
      <View style={styles.cardTopLine}>
        <Badge label={readableLabel(action.priority)} tone={colorForStatus(action.priority)} />
        <Text style={styles.amountText}>{formatCurrency(action.amount)}</Text>
      </View>
      <Text style={styles.cardTitle}>{action.label}</Text>
      <Text style={styles.cardMeta}>{action.restaurant_name}</Text>
      <Text style={styles.cardMeta}>{readableLabel(action.action_type)} - {formatDate(action.due_at)}</Text>
    </Pressable>
  );
}

function Metric({ label, value, light = false }: { label: string; value: string; light?: boolean }) {
  return (
    <View style={[styles.metric, light && styles.metricLight]}>
      <Text style={[styles.metricValue, light && styles.metricValueLight]}>{value}</Text>
      <Text style={[styles.metricLabel, light && styles.metricLabelLight]}>{label}</Text>
    </View>
  );
}

function QuickAction({ label, value, onPress }: { label: string; value: string; onPress: () => void }) {
  return (
    <Pressable style={styles.quickAction} onPress={onPress}>
      <Text style={styles.quickValue}>{value}</Text>
      <Text style={styles.quickLabel}>{label}</Text>
    </Pressable>
  );
}

function SectionHeader({ title, action, onPress }: { title: string; action?: string; onPress?: () => void }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {action && onPress ? (
        <Pressable onPress={onPress}>
          <Text style={styles.sectionAction}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Badge({ label, tone }: { label: string; tone: string }) {
  return (
    <View style={[styles.badge, { borderColor: tone, backgroundColor: `${tone}14` }]}>
      <Text style={[styles.badgeText, { color: tone }]}>{label}</Text>
    </View>
  );
}

function PrimaryButton({ label, onPress, disabled, danger }: { label: string; onPress: () => void; disabled?: boolean; danger?: boolean }) {
  return (
    <Pressable style={[styles.primaryButton, danger && styles.dangerButton, disabled && styles.disabledButton]} onPress={onPress} disabled={disabled}>
      <Text style={styles.primaryButtonText}>{label}</Text>
    </Pressable>
  );
}

function SecondaryButton({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable style={[styles.secondaryButton, disabled && styles.disabledButton]} onPress={onPress} disabled={disabled}>
      <Text style={styles.secondaryButtonText}>{label}</Text>
    </Pressable>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <View style={styles.emptyState}>
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

function LoadingState({ title }: { title: string }) {
  return (
    <View style={styles.loadingState}>
      <ActivityIndicator color={colors.primary} size="large" />
      <Text style={styles.emptyTitle}>{title}</Text>
    </View>
  );
}

function assetToFile(asset: ImagePicker.ImagePickerAsset, fallbackName: string, fallbackType: string): UploadableFile {
  return {
    uri: asset.uri,
    name: asset.fileName || fallbackName,
    type: asset.mimeType || fallbackType,
  };
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.canvas,
    paddingTop: Platform.OS === "android" ? NativeStatusBar.currentHeight ?? 0 : 0,
  },
  app: {
    flex: 1,
    backgroundColor: colors.canvas,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: Platform.OS === "android" ? 240 : 150,
  },
  stack: {
    gap: spacing.lg,
  },
  login: {
    flex: 1,
    padding: spacing.xl,
    justifyContent: "center",
    gap: spacing.lg,
  },
  logoMark: {
    width: 72,
    height: 72,
    borderRadius: 20,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  logoText: {
    color: colors.white,
    fontSize: 34,
    fontWeight: "900",
  },
  loginTitle: {
    fontSize: 42,
    fontWeight: "900",
    color: colors.ink,
    letterSpacing: 0,
  },
  loginSubtitle: {
    color: colors.inkMuted,
    fontSize: 17,
    lineHeight: 24,
  },
  formCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.line,
    ...shadow,
  },
  fieldLabel: {
    color: colors.ink,
    fontSize: 13,
    fontWeight: "800",
  },
  input: {
    minHeight: 52,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surfaceWarm,
    paddingHorizontal: spacing.lg,
    color: colors.ink,
    fontSize: 16,
  },
  securityNote: {
    color: colors.inkMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  },
  headerIdentity: {
    flex: 1,
    paddingRight: spacing.md,
    minWidth: 0,
  },
  headerEyebrow: {
    color: colors.primary,
    fontWeight: "900",
    fontSize: 12,
    textTransform: "uppercase",
  },
  headerTitle: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "900",
  },
  refreshButton: {
    minHeight: 42,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primarySoft,
  },
  refreshButtonText: {
    color: colors.primary,
    fontWeight: "900",
  },
  hero: {
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.lg,
    ...shadow,
  },
  heroKicker: {
    color: colors.gold,
    fontWeight: "900",
    textTransform: "uppercase",
    fontSize: 12,
  },
  heroTitle: {
    color: colors.white,
    fontSize: 26,
    lineHeight: 32,
    fontWeight: "900",
    letterSpacing: 0,
  },
  heroMetrics: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  quickGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  quickAction: {
    flex: 1,
    minWidth: 150,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.line,
    ...shadow,
  },
  quickValue: {
    color: colors.ink,
    fontSize: 22,
    fontWeight: "900",
  },
  quickLabel: {
    color: colors.inkMuted,
    fontSize: 13,
    marginTop: spacing.xs,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  sectionTitle: {
    color: colors.ink,
    fontSize: 20,
    fontWeight: "900",
  },
  sectionAction: {
    color: colors.primary,
    fontWeight: "900",
  },
  screenTitle: {
    color: colors.ink,
    fontSize: 30,
    fontWeight: "900",
    letterSpacing: 0,
  },
  screenSubtitle: {
    color: colors.inkMuted,
    fontSize: 16,
    lineHeight: 23,
  },
  listCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.line,
    gap: spacing.sm,
  },
  listCardSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  cardTopLine: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.sm,
  },
  cardTitle: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "900",
  },
  cardMeta: {
    color: colors.inkMuted,
    fontSize: 14,
  },
  amountText: {
    color: colors.ink,
    fontWeight: "900",
  },
  detailCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.line,
    gap: spacing.md,
    ...shadow,
  },
  detailTitle: {
    color: colors.ink,
    fontSize: 22,
    lineHeight: 28,
    fontWeight: "900",
  },
  detailMeta: {
    color: colors.inkMuted,
    fontSize: 15,
  },
  detailProof: {
    color: colors.primary,
    fontSize: 17,
    fontWeight: "900",
  },
  detailBody: {
    color: colors.ink,
    fontSize: 15,
    lineHeight: 22,
  },
  actionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  primaryButton: {
    flex: 1,
    minWidth: 150,
    minHeight: 52,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  dangerButton: {
    backgroundColor: colors.red,
  },
  secondaryButton: {
    flex: 1,
    minWidth: 150,
    minHeight: 52,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceWarm,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  disabledButton: {
    opacity: 0.5,
  },
  primaryButtonText: {
    color: colors.white,
    fontWeight: "900",
    fontSize: 15,
  },
  secondaryButtonText: {
    color: colors.ink,
    fontWeight: "900",
    fontSize: 15,
  },
  badge: {
    alignSelf: "flex-start",
    borderRadius: radius.pill,
    paddingVertical: 5,
    paddingHorizontal: 10,
    borderWidth: 1,
  },
  badgeText: {
    fontWeight: "900",
    fontSize: 12,
  },
  metricGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  metric: {
    flexGrow: 1,
    flexBasis: "45%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.line,
  },
  metricLight: {
    flex: 1,
    backgroundColor: "rgba(255,255,255,0.10)",
    borderColor: "rgba(255,255,255,0.24)",
  },
  metricValue: {
    color: colors.ink,
    fontSize: 19,
    fontWeight: "900",
  },
  metricValueLight: {
    color: colors.white,
  },
  metricLabel: {
    color: colors.inkMuted,
    fontSize: 12,
    marginTop: spacing.xs,
  },
  metricLabelLight: {
    color: "#DDEDE7",
  },
  emptyState: {
    borderRadius: radius.lg,
    padding: spacing.xl,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surfaceWarm,
    gap: spacing.sm,
  },
  loadingState: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.lg,
  },
  emptyTitle: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "900",
  },
  emptyBody: {
    color: colors.inkMuted,
    fontSize: 15,
    lineHeight: 22,
  },
  scannerCard: {
    height: 280,
    borderRadius: radius.lg,
    overflow: "hidden",
    backgroundColor: colors.ink,
    borderWidth: 1,
    borderColor: colors.line,
  },
  camera: {
    flex: 1,
  },
  cameraFallback: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    gap: spacing.md,
  },
  bottomNav: {
    position: "absolute",
    left: spacing.md,
    right: spacing.md,
    bottom: Platform.OS === "ios" ? spacing.lg : 76,
    minHeight: 64,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    flexDirection: "row",
    padding: spacing.xs,
    ...shadow,
  },
  navItem: {
    flex: 1,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 2,
  },
  navItemActive: {
    backgroundColor: colors.primary,
  },
  navText: {
    color: colors.inkMuted,
    fontSize: 11,
    fontWeight: "900",
  },
  navTextActive: {
    color: colors.white,
  },
});
