export type Printer = {
  id: string;
  asset_number: string;
  printer_model_id: string;
  department_id: string | null;
  location: string | null;
  active: boolean;
};

export type ServiceRequest = {
  id: string;
  request_number: string;
  created_by: string;
  printer_id: string;
  request_type: string;
  description: string;
  status: string;
  created_at: string;
};

export type Cartridge = {
  id: string;
  asset_code: string;
  cartridge_model_id: string;
  cartridge_model: { manufacturer: string; model_name: string };
  serial_number: string | null;
  status: string;
  created_at: string;
};

export type CartridgeModel = {
  id: string;
  manufacturer: string;
  model_name: string;
};

export type CartridgeMovement = {
  id: string;
  request_id: string | null;
  actor_id: string;
  movement_type: string;
  from_user_id: string | null;
  to_user_id: string | null;
  from_status: string | null;
  to_status: string;
  counter_reading: number | null;
  condition: string | null;
  note: string | null;
  created_at: string;
};

export type CartridgeInstallation = {
  id: string;
  request_id: string;
  installed_by: string;
  install_counter: number | null;
  condition_at_install: string | null;
  installed_at: string;
  cartridge: Cartridge;
  printer: Printer;
};

type DevIdentity = { userId: string; roles: string[] };

const identityKey = "uniprint-dev-identity-v1";

export function readDevIdentity(): DevIdentity {
  if (!import.meta.env.DEV) return { userId: "", roles: ["employee"] };
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(identityKey) ?? "null");
    if (
      typeof value === "object" && value !== null &&
      "userId" in value && typeof value.userId === "string" &&
      "roles" in value && Array.isArray(value.roles) && value.roles.every((role) => typeof role === "string")
    ) {
      return { userId: value.userId, roles: value.roles };
    }
  } catch {
    sessionStorage.removeItem(identityKey);
  }
  return { userId: "", roles: ["employee"] };
}

export function saveDevIdentity(identity: DevIdentity): void {
  if (import.meta.env.DEV) sessionStorage.setItem(identityKey, JSON.stringify(identity));
}

async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (import.meta.env.DEV) {
    const identity = readDevIdentity();
    if (identity.userId) {
      headers.set("X-Dev-User-Id", identity.userId);
      headers.set("X-Dev-Roles", identity.roles.join(","));
    }
  }
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Запит не виконано (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Keep the generic status message for non-JSON responses.
    }
    throw new Error(message);
  }
  return response;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiResponse(path, init);
  return response.json() as Promise<T>;
}

export async function apiBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const response = await apiResponse(path, init);
  return response.blob();
}
