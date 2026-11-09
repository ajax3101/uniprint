import { useEffect, useMemo, useState } from "react";
import { api, apiBlob, readDevIdentity, saveDevIdentity, type Cartridge, type CartridgeInstallation, type CartridgeModel, type Printer, type ServiceRequest } from "./api";

type Page = "overview" | "requests" | "printers" | "cartridges";

const pageTitles: Record<Page, string> = {
  overview: "Огляд",
  requests: "Заявки",
  printers: "Принтери",
  cartridges: "Картриджі",
};

const requestLabels: Record<string, string> = {
  refill: "Заправлення",
  replacement: "Заміна картриджа",
  repair: "Ремонт",
  maintenance: "Обслуговування",
  other: "Інше",
};

const statusLabels: Record<string, string> = {
  submitted: "Нова",
  in_review: "На погодженні",
  approved: "Погоджена",
  rejected: "Відхилена",
  processing: "В роботі",
  fulfilled: "Виконана",
  completed: "Закрита",
  cancelled: "Скасована",
  in_stock: "На складі",
  sent_for_refill: "На заправці",
  in_repair: "У ремонті",
  pending_inspection: "Очікує перевірки",
  installed: "Встановлений",
  written_off: "Списаний",
  issued: "Виданий",
  active: "В обліку",
  inactive: "Неактивний",
};

const movementLabels: Record<string, string> = {
  receipt: "Приймання",
  issue: "Видача",
  install: "Встановлення",
  remove: "Зняття",
  return: "Повернення",
  refill_return: "Повернення із заправки",
  repair_return: "Повернення з ремонту",
  inspection: "Інспекція",
};

const nextAction: Record<string, { target: string; label: string; role: string[] }> = {
  submitted: { target: "in_review", label: "Взяти на розгляд", role: ["approver", "technician", "admin"] },
  in_review: { target: "approved", label: "Погодити", role: ["approver", "admin"] },
  approved: { target: "processing", label: "Почати виконання", role: ["technician", "admin"] },
  processing: { target: "fulfilled", label: "Позначити виконаною", role: ["technician", "storekeeper", "admin"] },
  fulfilled: { target: "completed", label: "Закрити заявку", role: ["employee", "admin"] },
};

function App() {
  const [page, setPage] = useState<Page>("overview");
  const [requests, setRequests] = useState<ServiceRequest[]>([]);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [cartridges, setCartridges] = useState<Cartridge[]>([]);
  const [cartridgeModels, setCartridgeModels] = useState<CartridgeModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requestType, setRequestType] = useState("refill");
  const [printerId, setPrinterId] = useState("");
  const [description, setDescription] = useState("");
  const [identity, setIdentity] = useState(readDevIdentity);
  const [showIdentity, setShowIdentity] = useState(false);

  const printerById = useMemo(() => new Map(printers.map((printer) => [printer.id, printer])), [printers]);
  const recentRequests = requests.slice(0, 5);

  async function refresh(signal?: AbortSignal) {
    setLoading(true);
    setError("");
    try {
      const [requestRows, printerRows, cartridgeRows, modelRows] = await Promise.all([
        api<ServiceRequest[]>("/requests", { signal }),
        api<Printer[]>("/printers", { signal }),
        api<Cartridge[]>("/cartridges", { signal }),
        api<CartridgeModel[]>("/cartridge-models", { signal }),
      ]);
      setRequests(requestRows);
      setPrinters(printerRows);
      setCartridges(cartridgeRows);
      setCartridgeModels(modelRows);
      setPrinterId((current) => current || printerRows[0]?.id || "");
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "Не вдалося завантажити дані.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, []);

  function updateIdentity(field: "userId" | "roles", value: string) {
    const updated = field === "userId"
      ? { ...identity, userId: value }
      : { ...identity, roles: value.split(",").map((role) => role.trim()).filter(Boolean) };
    setIdentity(updated);
    saveDevIdentity(updated);
  }

  async function createRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!printerId) {
      setError("Спочатку додайте принтер до реєстру.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api<ServiceRequest>("/requests", {
        method: "POST",
        body: JSON.stringify({ printer_id: printerId, request_type: requestType, description }),
      });
      setDescription("");
      setNotice("Заявку створено й передано на погодження.");
      await refresh();
      setPage("requests");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося створити заявку.");
    } finally {
      setSaving(false);
    }
  }

  async function transitionRequest(request: ServiceRequest, target: string) {
    setError("");
    setNotice("");
    try {
      await api<ServiceRequest>(`/requests/${request.id}/transitions`, {
        method: "POST",
        body: JSON.stringify({ target_status: target }),
      });
      setNotice("Статус заявки оновлено.");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося оновити заявку.");
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={() => setPage("overview")} aria-label="UniPrint — на головну">
          <span className="brand-mark" aria-hidden="true">U</span>
          <span><strong>UniPrint</strong><small>Облік друку</small></span>
        </a>
        <div className="nav-label">РОБОЧИЙ ПРОСТІР</div>
        <nav aria-label="Головна навігація">
          {(Object.keys(pageTitles) as Page[]).map((key) => (
            <button className={`nav-item ${page === key ? "active" : ""}`} key={key} onClick={() => setPage(key)}>
              <span className={`nav-icon nav-icon-${key}`} aria-hidden="true" />
              <span className="nav-text">{pageTitles[key]}</span>
              {key === "requests" && requests.filter((request) => request.status === "submitted").length > 0 && (
                <span className="nav-count">{requests.filter((request) => request.status === "submitted").length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">Облік друку</div>
          <div className="user-card">
            <span className="avatar">{identity.userId ? identity.userId.slice(0, 1).toUpperCase() : "?"}</span>
            <span><strong>{identity.userId || "Не авторизовано"}</strong><small>{identity.roles.join(", ")}</small></span>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs"><span>UniPrint</span><span className="crumb-separator">/</span><strong>{pageTitles[page]}</strong></div>
          <div className="topbar-actions">
            {import.meta.env.DEV && <button className="text-button" onClick={() => setShowIdentity((open) => !open)}>Локальна сесія</button>}
            <span className="topbar-avatar">{identity.userId ? identity.userId.slice(0, 1).toUpperCase() : "?"}</span>
          </div>
        </header>

        {showIdentity && import.meta.env.DEV && (
          <section className="dev-panel" aria-label="Локальна тестова ідентичність">
            <div><strong>Локальний режим розробки</strong><p>Працює лише з loopback API та синтетичним користувачем.</p></div>
            <label>ID користувача<input value={identity.userId} onChange={(event) => updateIdentity("userId", event.target.value)} placeholder="dev-operator" /></label>
            <label>Ролі через кому<input value={identity.roles.join(", ")} onChange={(event) => updateIdentity("roles", event.target.value)} placeholder="employee, approver" /></label>
          </section>
        )}

        <div className="page-wrap">
          <div className="page-heading">
            <div><p className="eyebrow">УПРАВЛІННЯ ДРУКОМ УНІВЕРСИТЕТУ</p><h1>{page === "overview" ? "Вітаємо в UniPrint" : pageTitles[page]}</h1>
              <p className="page-subtitle">Заявки, обладнання та рух картриджів — в одному робочому просторі.</p></div>
            <button className="button button-primary" onClick={() => setPage("requests")}><span aria-hidden="true">＋</span> Нова заявка</button>
          </div>

          {error && <div className="alert alert-error" role="alert"><span>{error}</span><button onClick={() => void refresh()}>Повторити</button></div>}
          {notice && <div className="alert alert-success" role="status">{notice}</div>}

          {loading ? <div className="loading-card"><span className="spinner" />Завантажуємо робочий простір…</div> : (
            <>
              {page === "overview" && <Overview requests={requests} printers={printers} cartridges={cartridges} recentRequests={recentRequests} printerById={printerById} onOpenRequests={() => setPage("requests")} />}
              {page === "requests" && <RequestsPage requests={requests} printers={printerById} canAct={identity.roles} onCreate={createRequest} onTransition={transitionRequest} onRefresh={refresh} saving={saving} requestType={requestType} setRequestType={setRequestType} printerId={printerId} setPrinterId={setPrinterId} description={description} setDescription={setDescription} availablePrinters={printers} />}
              {page === "printers" && <PrintersPage printers={printers} />}
              {page === "cartridges" && <CartridgesPage cartridges={cartridges} models={cartridgeModels} roles={identity.roles} onRefresh={refresh} />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Overview({ requests, printers, cartridges, recentRequests, printerById, onOpenRequests }: {
  requests: ServiceRequest[];
  printers: Printer[];
  cartridges: Cartridge[];
  recentRequests: ServiceRequest[];
  printerById: Map<string, Printer>;
  onOpenRequests: () => void;
}) {
  const pending = requests.filter((request) => ["submitted", "in_review", "approved", "processing"].includes(request.status)).length;
  const stock = cartridges.filter((cartridge) => cartridge.status === "in_stock").length;
  return <>
    <section className="stats-grid" aria-label="Ключові показники">
      <StatCard label="Активні заявки" value={pending} note="Потребують уваги" icon="↗" tone="blue" />
      <StatCard label="Принтери в реєстрі" value={printers.length} note="Зареєстроване обладнання" icon="▤" tone="green" />
      <StatCard label="Картриджі на складі" value={stock} note={`Усього екземплярів: ${cartridges.length}`} icon="▣" tone="amber" />
    </section>
    <section className="content-grid">
      <div className="panel request-panel">
        <div className="panel-heading"><div><h2>Останні заявки</h2><p>Нещодавня активність за вашими доступами</p></div><button className="link-button" onClick={onOpenRequests}>Усі заявки <span aria-hidden="true">→</span></button></div>
        <RequestTable rows={recentRequests} printers={printerById} />
      </div>
      <aside className="panel quick-panel">
        <div className="panel-heading"><div><h2>Швидка заявка</h2><p>Повідомте про потребу в обслуговуванні</p></div></div>
        <div className="quick-illustration" aria-hidden="true"><span className="printer-shape"><i /></span><span className="spark spark-one">✦</span><span className="spark spark-two">✦</span></div>
        <p className="quick-copy">Створіть заявку, щоб команда підтримки могла розпочати роботу.</p>
        <button className="button button-outline full-width" onClick={onOpenRequests}>Створити заявку <span aria-hidden="true">→</span></button>
      </aside>
    </section>
  </>;
}

function StatCard({ label, value, note, icon, tone }: { label: string; value: number; note: string; icon: string; tone: string }) {
  return <article className="stat-card"><div className={`stat-icon ${tone}`} aria-hidden="true">{icon}</div><p>{label}</p><div className="stat-value">{value}</div><span className="stat-note">{note}</span></article>;
}

function RequestTable({ rows, printers }: { rows: ServiceRequest[]; printers: Map<string, Printer> }) {
  if (!rows.length) return <div className="empty-state"><span className="empty-icon">▤</span><strong>Заявок ще немає</strong><span>Створіть першу заявку, щоб розпочати роботу.</span></div>;
  return <div className="table-scroll"><table><thead><tr><th>НОМЕР</th><th>ТИП</th><th>ПРИНТЕР</th><th>СТАТУС</th><th>СТВОРЕНО</th></tr></thead><tbody>
    {rows.map((request) => <tr key={request.id}><td><strong className="request-number">{request.request_number}</strong></td><td>{requestLabels[request.request_type] ?? request.request_type}</td><td>{printers.get(request.printer_id)?.asset_number ?? "—"}</td><td><StatusBadge status={request.status} /></td><td>{new Date(request.created_at).toLocaleDateString("uk-UA")}</td></tr>)}
  </tbody></table></div>;
}

function RequestsPage({ requests, printers, canAct, onCreate, onTransition, onRefresh, saving, requestType, setRequestType, printerId, setPrinterId, description, setDescription, availablePrinters }: {
  requests: ServiceRequest[];
  printers: Map<string, Printer>;
  canAct: string[];
  onCreate: (event: React.FormEvent<HTMLFormElement>) => void;
  onTransition: (request: ServiceRequest, target: string) => void;
  onRefresh: () => Promise<void>;
  saving: boolean;
  requestType: string;
  setRequestType: (value: string) => void;
  printerId: string;
  setPrinterId: (value: string) => void;
  description: string;
  setDescription: (value: string) => void;
  availablePrinters: Printer[];
}) {
  return <section className="panel page-panel">
    <div className="panel-heading"><div><h2>Усі заявки</h2><p>Створення звернень і контроль поточних етапів.</p></div><span className="small-count">{requests.length} записів</span></div>
    <form className="request-form" onSubmit={onCreate}>
      <label>Принтер<select value={printerId} onChange={(event) => setPrinterId(event.target.value)} required><option value="">Оберіть принтер</option>{availablePrinters.map((printer) => <option value={printer.id} key={printer.id}>{printer.asset_number} · {printer.location ?? "місце не вказане"}</option>)}</select></label>
      <label>Тип звернення<select value={requestType} onChange={(event) => setRequestType(event.target.value)}><option value="refill">Заправлення</option><option value="replacement">Заміна картриджа</option><option value="repair">Ремонт</option><option value="maintenance">Обслуговування</option><option value="other">Інше</option></select></label>
      <label className="form-wide">Опис<textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} rows={2} placeholder="Опишіть, що потрібно зробити" /></label>
      <div className="form-submit"><button className="button button-primary" disabled={saving || !availablePrinters.length}>{saving ? "Надсилаємо…" : "Надіслати заявку"}</button></div>
    </form>
    <div className="table-scroll"><table><thead><tr><th>НОМЕР</th><th>ТИП</th><th>ПРИНТЕР</th><th>СТАТУС</th><th>ДІЯ</th></tr></thead><tbody>
      {requests.map((request) => {
        const action = nextAction[request.status];
        const allowed = action && action.role.some((role) => canAct.includes(role));
        return <RequestRow key={request.id} request={request} printer={printers.get(request.printer_id)} action={allowed ? action : undefined} canStore={canAct.includes("storekeeper") || canAct.includes("admin")} canInstall={canAct.some((role) => ["employee", "technician", "admin"].includes(role))} canRemove={canAct.some((role) => ["technician", "storekeeper", "admin"].includes(role))} canAdmin={canAct.includes("admin")} onTransition={onTransition} onRefresh={() => void onRefresh()} />;
      })}
      {!requests.length && <tr><td colSpan={5}><div className="table-empty">Заявок поки немає.</div></td></tr>}
    </tbody></table></div>
  </section>;
}

function RequestRow({ request, printer, action, canStore, canInstall, canRemove, canAdmin, onTransition, onRefresh }: {
  request: ServiceRequest;
  printer?: Printer;
  action?: { target: string; label: string; role: string[] };
  canStore: boolean;
  canInstall: boolean;
  canRemove: boolean;
  canAdmin: boolean;
  onTransition: (request: ServiceRequest, target: string) => void;
  onRefresh: () => void;
}) {
  const [issueCode, setIssueCode] = useState("");
  const [returnCode, setReturnCode] = useState("");
  const [installCode, setInstallCode] = useState("");
  const [removeCode, setRemoveCode] = useState("");
  const [installCounter, setInstallCounter] = useState("");
  const [removeCounter, setRemoveCounter] = useState("");
  const [outcome, setOutcome] = useState("stock");
  const [counter, setCounter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");

  async function issue() {
    if (!issueCode.trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await api(`/requests/${request.id}/issue`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ cartridge_code: issueCode.trim(), recipient_id: request.created_by }),
      });
      setIssueCode("");
      setMessage("Картридж видано.");
      onRefresh();
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : "Не вдалося видати картридж.");
    } finally {
      setBusy(false);
    }
  }

  async function returnCartridge() {
    if (!returnCode.trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await api(`/requests/${request.id}/return`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          cartridge_code: returnCode.trim(),
          recipient_id: request.created_by,
          outcome,
          counter_reading: counter ? Number(counter) : null,
        }),
      });
      setReturnCode("");
      setCounter("");
      setMessage(outcome === "refill" ? "Картридж передано на заправку." : "Повернення зареєстровано.");
      onRefresh();
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : "Не вдалося зареєструвати повернення.");
    } finally {
      setBusy(false);
    }
  }

  async function installCartridge() {
    if (!installCode.trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await api(`/requests/${request.id}/install`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ cartridge_code: installCode.trim(), counter_reading: installCounter ? Number(installCounter) : null }),
      });
      setInstallCode("");
      setInstallCounter("");
      setMessage("Встановлення картриджа зафіксовано.");
      onRefresh();
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : "Не вдалося зафіксувати встановлення.");
    } finally {
      setBusy(false);
    }
  }

  async function removeCartridge() {
    if (!removeCode.trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await api(`/requests/${request.id}/remove`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ cartridge_code: removeCode.trim(), counter_reading: removeCounter ? Number(removeCounter) : null }),
      });
      setRemoveCode("");
      setRemoveCounter("");
      setMessage("Зняття картриджа зафіксовано.");
      onRefresh();
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : "Не вдалося зафіксувати зняття.");
    } finally {
      setBusy(false);
    }
  }

  const mayIssue = canStore && request.status === "approved";
  const mayReturn = canStore && ["processing", "fulfilled"].includes(request.status);
  const mayInstall = canInstall && request.status === "processing";
  const mayRemove = canRemove && request.status === "processing";
  return <tr>
    <td><strong className="request-number">{request.request_number}</strong></td>
    <td>{requestLabels[request.request_type] ?? request.request_type}</td>
    <td>{printer?.asset_number ?? "—"}</td>
    <td><StatusBadge status={request.status} /></td>
    <td><div className="row-operations">
      {action && <button className="table-action" onClick={() => onTransition(request, action.target)}>{action.label}</button>}
      {mayIssue && <div className="scan-operation"><label htmlFor={`issue-${request.id}`}>Видати: скануйте код картриджа</label><div><input id={`issue-${request.id}`} value={issueCode} onChange={(event) => setIssueCode(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void issue(); } }} placeholder="Код картриджа" /><button className="table-action" disabled={busy || !issueCode.trim()} onClick={() => void issue()}>{busy ? "…" : "Видати"}</button></div></div>}
      {mayInstall && <div className="scan-operation"><label htmlFor={`install-${request.id}`}>Підтвердити встановлення</label><div><input id={`install-${request.id}`} value={installCode} onChange={(event) => setInstallCode(event.target.value)} placeholder="Код картриджа" /><input aria-label="Показання лічильника під час встановлення" type="number" min="0" value={installCounter} onChange={(event) => setInstallCounter(event.target.value)} placeholder="Лічильник" /><button className="table-action" disabled={busy || !installCode.trim()} onClick={() => void installCartridge()}>{busy ? "…" : "Встановити"}</button></div></div>}
      {mayRemove && <div className="scan-operation"><label htmlFor={`remove-${request.id}`}>Зняти картридж для повернення</label><div><input id={`remove-${request.id}`} value={removeCode} onChange={(event) => setRemoveCode(event.target.value)} placeholder="Код картриджа" /><input aria-label="Показання лічильника під час зняття" type="number" min="0" value={removeCounter} onChange={(event) => setRemoveCounter(event.target.value)} placeholder="Лічильник" /><button className="table-action" disabled={busy || !removeCode.trim()} onClick={() => void removeCartridge()}>{busy ? "…" : "Зняти"}</button></div></div>}
      {mayReturn && <div className="scan-operation"><label htmlFor={`return-${request.id}`}>Повернути: скануйте код картриджа</label><div><input id={`return-${request.id}`} value={returnCode} onChange={(event) => setReturnCode(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void returnCartridge(); } }} placeholder="Код картриджа" /><select aria-label="Подальша дія з картриджем" value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="stock">На склад</option><option value="refill">На заправку</option><option value="repair">У ремонт</option>{canAdmin && <option value="writeoff">Списати</option>}</select><input aria-label="Показання лічильника" type="number" min="0" value={counter} onChange={(event) => setCounter(event.target.value)} placeholder="Лічильник" /><button className="table-action" disabled={busy || !returnCode.trim()} onClick={() => void returnCartridge()}>{busy ? "…" : "Повернути"}</button></div></div>}
      {message && <span className="operation-success" role="status">{message}</span>}{failure && <span className="operation-error" role="alert">{failure}</span>}
    </div></td>
  </tr>;
}

function PrintersPage({ printers }: { printers: Printer[] }) {
  return <section className="panel page-panel"><div className="panel-heading"><div><h2>Реєстр принтерів</h2><p>Обладнання, доступне у вашому обліковому записі.</p></div><span className="small-count">{printers.length} пристроїв</span></div>
    <div className="table-scroll"><table><thead><tr><th>ІНВЕНТАРНИЙ НОМЕР</th><th>МІСЦЕ</th><th>ПІДРОЗДІЛ</th><th>СТАН</th></tr></thead><tbody>{printers.map((printer) => <tr key={printer.id}><td><strong>{printer.asset_number}</strong></td><td>{printer.location ?? "Не вказано"}</td><td>{printer.department_id ?? "—"}</td><td><StatusBadge status={printer.active ? "active" : "inactive"} /></td></tr>)}{!printers.length && <tr><td colSpan={4}><div className="table-empty">Реєстр поки порожній.</div></td></tr>}</tbody></table></div>
  </section>;
}

function CartridgesPage({ cartridges, models, roles, onRefresh }: {
  cartridges: Cartridge[];
  models: CartridgeModel[];
  roles: string[];
  onRefresh: () => Promise<void>;
}) {
  const [receiptCode, setReceiptCode] = useState("");
  const [refillCode, setRefillCode] = useState("");
  const [repairCode, setRepairCode] = useState("");
  const [inspectionCode, setInspectionCode] = useState("");
  const [modelId, setModelId] = useState("");
  const [serialNumber, setSerialNumber] = useState("");
  const [refillProvider, setRefillProvider] = useState("");
  const [refillCost, setRefillCost] = useState("");
  const [refillTestResult, setRefillTestResult] = useState("");
  const [repairProvider, setRepairProvider] = useState("");
  const [repairCost, setRepairCost] = useState("");
  const [repairTestResult, setRepairTestResult] = useState("");
  const [inspectionResult, setInspectionResult] = useState("stock");
  const [installations, setInstallations] = useState<CartridgeInstallation[]>([]);
  const [historyCode, setHistoryCode] = useState("");
  const [history, setHistory] = useState<import("./api").CartridgeMovement[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const canStore = roles.includes("storekeeper") || roles.includes("admin");
  const canService = roles.some((role) => ["technician", "storekeeper", "admin"].includes(role));
  const canAdmin = roles.includes("admin");

  useEffect(() => {
    if (!canService) return;
    const controller = new AbortController();
    void api<CartridgeInstallation[]>("/installations", { signal: controller.signal })
      .then(setInstallations)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Не вдалося завантажити встановлення.");
      });
    return () => controller.abort();
  }, [canService]);

  async function runOperation(path: string, body: object, success: string): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(path, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(body) });
      setNotice(success);
      await onRefresh();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Операцію не виконано.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function receive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!await runOperation("/cartridges", { asset_code: receiptCode.trim(), cartridge_model_id: modelId, serial_number: serialNumber || null }, "Картридж прийнято на склад.")) return;
    setReceiptCode("");
    setSerialNumber("");
  }

  async function completeRefill(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!await runOperation(`/cartridges/${encodeURIComponent(refillCode.trim())}/refill-completion`, {
      provider: refillProvider || null,
      cost: refillCost ? Number(refillCost) : null,
      currency: refillCost ? "UAH" : null,
      test_result: refillTestResult.trim(),
    }, "Заправку завершено. Картридж очікує інспекції.")) return;
    setRefillProvider("");
    setRefillCost("");
    setRefillTestResult("");
  }

  async function completeRepair(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!await runOperation(`/cartridges/${encodeURIComponent(repairCode.trim())}/repair-completion`, {
      provider: repairProvider || null,
      cost: repairCost ? Number(repairCost) : null,
      currency: repairCost ? "UAH" : null,
      test_result: repairTestResult.trim(),
    }, "Ремонт завершено. Картридж очікує інспекції.")) return;
    setRepairProvider("");
    setRepairCost("");
    setRepairTestResult("");
  }

  async function inspect(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runOperation(`/cartridges/${encodeURIComponent(inspectionCode.trim())}/inspection`, { result: inspectionResult }, "Результат інспекції записано.");
  }

  async function loadHistory(code = historyCode) {
    if (!code.trim()) return;
    setError("");
    try {
      setHistory(await api(`/cartridges/${encodeURIComponent(code.trim())}/events`));
      setHistoryCode(code.trim());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося завантажити історію.");
      setHistory(null);
    }
  }

  async function downloadLabel(code: string) {
    setError("");
    try {
      const blob = await apiBlob(`/cartridges/${encodeURIComponent(code)}/label.svg`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${code}-label.svg`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося створити етикетку.");
    }
  }

  return <>
    <section className="panel page-panel">
      <div className="panel-heading"><div><h2>Фізичні картриджі</h2><p>Екземпляри та поточний стан складського обліку.</p></div><span className="small-count">{cartridges.length} екземплярів</span></div>
      {(error || notice) && <div className={`alert ${error ? "alert-error" : "alert-success"}`} role={error ? "alert" : "status"}>{error || notice}</div>}
      {canService && <section className="active-installations" aria-label="Встановлені картриджі"><div className="panel-heading"><div><h2>Активні встановлення</h2><p>Картриджі, які зараз обліковуються у принтерах.</p></div><span className="small-count">{installations.length}</span></div>
        <div className="table-scroll"><table><thead><tr><th>ПРИНТЕР</th><th>КАРТРИДЖ</th><th>ВСТАНОВЛЕНО</th><th>ПОЧАТКОВИЙ ЛІЧИЛЬНИК</th><th>ЗАЯВКА</th></tr></thead><tbody>{installations.map((installation) => <tr key={installation.id}><td><strong>{installation.printer.asset_number}</strong> · {installation.printer.location ?? "місце не вказане"}</td><td>{installation.cartridge.asset_code} · {installation.cartridge.cartridge_model.model_name}</td><td>{new Date(installation.installed_at).toLocaleString("uk-UA")}</td><td>{installation.install_counter ?? "—"}</td><td>{installation.request_id}</td></tr>)}{!installations.length && <tr><td colSpan={5}><div className="table-empty">Активних встановлень поки немає.</div></td></tr>}</tbody></table></div>
      </section>}
      <div className="cartridge-operations">
        {canStore && <form className="operation-form" onSubmit={(event) => void receive(event)}>
          <h3>Приймання на склад</h3>
          <label>Модель<select value={modelId} onChange={(event) => setModelId(event.target.value)} required><option value="">Оберіть модель</option>{models.map((model) => <option key={model.id} value={model.id}>{model.manufacturer} {model.model_name}</option>)}</select></label>
          <label>Код картриджа<input value={receiptCode} onChange={(event) => setReceiptCode(event.target.value)} required maxLength={100} /></label>
          <label>Серійний номер<input value={serialNumber} onChange={(event) => setSerialNumber(event.target.value)} maxLength={160} /></label>
          <button className="table-action" disabled={busy || !models.length}>Прийняти</button>
        </form>}
        {canService && <form className="operation-form" onSubmit={(event) => void completeRefill(event)}>
          <h3>Завершення заправки</h3>
          <label>Код картриджа<input value={refillCode} onChange={(event) => setRefillCode(event.target.value)} required maxLength={100} /></label>
          <label>Виконавець<input value={refillProvider} onChange={(event) => setRefillProvider(event.target.value)} maxLength={200} /></label>
          <label>Вартість, грн<input type="number" min="0" step="0.01" value={refillCost} onChange={(event) => setRefillCost(event.target.value)} /></label>
          <label>Результат перевірки<input value={refillTestResult} onChange={(event) => setRefillTestResult(event.target.value)} required maxLength={1000} /></label>
          <button className="table-action" disabled={busy}>Передати на інспекцію</button>
        </form>}
        {canService && <form className="operation-form" onSubmit={(event) => void completeRepair(event)}>
          <h3>Завершення ремонту</h3>
          <label>Код картриджа<input value={repairCode} onChange={(event) => setRepairCode(event.target.value)} required maxLength={100} /></label>
          <label>Виконавець<input value={repairProvider} onChange={(event) => setRepairProvider(event.target.value)} maxLength={200} /></label>
          <label>Вартість, грн<input type="number" min="0" step="0.01" value={repairCost} onChange={(event) => setRepairCost(event.target.value)} /></label>
          <label>Результат тесту<input value={repairTestResult} onChange={(event) => setRepairTestResult(event.target.value)} required maxLength={1000} /></label>
          <button className="table-action" disabled={busy}>Передати на інспекцію</button>
        </form>}
        {canService && <form className="operation-form" onSubmit={(event) => void inspect(event)}>
          <h3>Інспекція після заправки</h3>
          <label>Код картриджа<input value={inspectionCode} onChange={(event) => setInspectionCode(event.target.value)} required maxLength={100} /></label>
          <label>Результат<select value={inspectionResult} onChange={(event) => setInspectionResult(event.target.value)}><option value="stock">Повернути на склад</option><option value="repair">Передати в ремонт</option>{canAdmin && <option value="writeoff">Списати</option>}</select></label>
          <button className="table-action" disabled={busy}>Зберегти інспекцію</button>
        </form>}
      </div>
      <div className="table-scroll"><table><thead><tr><th>КОД</th><th>МОДЕЛЬ</th><th>СЕРІЙНИЙ НОМЕР</th><th>СТАТУС</th>{canStore && <th>QR-ЕТИКЕТКА</th>}{canService && <th>ІСТОРІЯ</th>}</tr></thead><tbody>{cartridges.map((cartridge) => <tr key={cartridge.id}><td><strong className="request-number">{cartridge.asset_code}</strong></td><td>{cartridge.cartridge_model.manufacturer} {cartridge.cartridge_model.model_name}</td><td>{cartridge.serial_number ?? "—"}</td><td><StatusBadge status={cartridge.status} /></td>{canStore && <td><button className="table-action" onClick={() => void downloadLabel(cartridge.asset_code)}>Завантажити SVG</button></td>}{canService && <td><button className="table-action" onClick={() => void loadHistory(cartridge.asset_code)}>Переглянути</button></td>}</tr>)}{!cartridges.length && <tr><td colSpan={4 + Number(canStore) + Number(canService)}><div className="table-empty">Картриджів поки немає.</div></td></tr>}</tbody></table></div>
    </section>
    {history && <section className="panel page-panel history-panel"><div className="panel-heading"><div><h2>Історія картриджа {historyCode}</h2><p>Незмінювані записи складських операцій.</p></div><span className="small-count">{history.length} подій</span></div>
      <div className="table-scroll"><table><thead><tr><th>ДАТА</th><th>ОПЕРАЦІЯ</th><th>ЗМІНА СТАНУ</th><th>КОРИСТУВАЧ / ЗАЯВКА</th><th>ПОКАЗАННЯ</th><th>ПРИМІТКА</th></tr></thead><tbody>{history.map((event) => <tr key={event.id}><td>{new Date(event.created_at).toLocaleString("uk-UA")}</td><td>{movementLabels[event.movement_type] ?? event.movement_type}</td><td>{statusLabels[event.from_status ?? ""] ?? event.from_status ?? "—"} → {statusLabels[event.to_status] ?? event.to_status}</td><td>{event.actor_id}{event.request_id ? ` · ${event.request_id}` : ""}</td><td>{event.counter_reading ?? "—"}</td><td>{event.note ?? event.condition ?? "—"}</td></tr>)}{!history.length && <tr><td colSpan={6}><div className="table-empty">Історія ще порожня.</div></td></tr>}</tbody></table></div>
    </section>}
  </>;
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === "approved" || status === "fulfilled" || status === "completed" || status === "in_stock" || status === "active" ? "positive" : status === "rejected" || status === "cancelled" || status === "inactive" ? "negative" : "neutral";
  return <span className={`status-badge ${tone}`}><span />{statusLabels[status] ?? status}</span>;
}

export default App;
