export type Environment = "production" | "ote";

export interface DomainListOptions {
  statuses?: string[];
  statusGroups?: string[];
  limit?: number;
  marker?: string;
  modifiedAtAfter?: string;
  expiresAtBefore?: string;
  includes?: string[];
}

export interface DomainUpdateOptions {
  renewAuto?: boolean;
  locked?: boolean;
  exposeWhois?: boolean;
}

export interface DnsRecord {
  type: string;
  name: string;
  data: string;
  ttl?: number;
  priority?: number;
}

export interface Address {
  address1: string;
  address2?: string;
  city: string;
  state: string;
  postalCode: string;
  country: string;
}

export interface Contact {
  nameFirst: string;
  nameLast: string;
  nameMiddle?: string;
  organization?: string;
  email: string;
  phone: string;
  fax?: string;
  addressMailing: Address;
  exposeWhois?: boolean;
}

export interface DomainContacts {
  registrant?: Contact;
  admin?: Contact;
  billing?: Contact;
  tech?: Contact;
}

export interface DomainRegistration {
  domain: string;
  period: number;
  nameServers?: string[];
  contacts: DomainContacts;
  privacy?: boolean;
  renewAuto?: boolean;
}

export class BrandSightClient {
  private baseUrl: string;
  private authHeader: string;
  private customerId: string;

  constructor(
    apiKey: string,
    apiSecret: string,
    customerId: string,
    environment: Environment = "production"
  ) {
    this.baseUrl =
      environment === "ote"
        ? "https://api.ote-godaddy.com"
        : "https://api.godaddy.com";
    this.authHeader = `sso-key ${apiKey}:${apiSecret}`;
    this.customerId = customerId;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const response = await fetch(url, {
      method,
      headers: {
        Authorization: this.authHeader,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (response.status === 204) return {} as T;

    const json = await response.json().catch(() => null);

    if (!response.ok) {
      const message =
        json?.message ?? json?.code ?? `HTTP ${response.status} ${response.statusText}`;
      throw new Error(`BrandSight API error: ${message}`);
    }

    return json as T;
  }

  // ── Domains ──────────────────────────────────────────────────────────────

  async listDomains(options: DomainListOptions = {}) {
    const params = new URLSearchParams();
    if (options.statuses?.length) params.set("statuses", options.statuses.join(","));
    if (options.statusGroups?.length) params.set("statusGroups", options.statusGroups.join(","));
    if (options.limit) params.set("limit", String(options.limit));
    if (options.marker) params.set("marker", options.marker);
    if (options.modifiedAtAfter) params.set("modifiedAtAfter", options.modifiedAtAfter);
    if (options.expiresAtBefore) params.set("expiresAtBefore", options.expiresAtBefore);
    if (options.includes?.length) params.set("includes", options.includes.join(","));
    const qs = params.toString();
    return this.request<unknown[]>(
      "GET",
      `/v2/customers/${this.customerId}/domains${qs ? "?" + qs : ""}`
    );
  }

  async getDomain(domain: string, includes?: string[]) {
    const qs = includes?.length ? `?includes=${includes.join(",")}` : "";
    return this.request<Record<string, unknown>>(
      "GET",
      `/v2/customers/${this.customerId}/domains/${domain}${qs}`
    );
  }

  async updateDomain(domain: string, updates: DomainUpdateOptions) {
    return this.request<unknown>(
      "PATCH",
      `/v2/customers/${this.customerId}/domains/${domain}`,
      updates
    );
  }

  // ── Availability ──────────────────────────────────────────────────────────

  async checkAvailability(domain: string) {
    return this.request<unknown>(
      "GET",
      `/v2/domains/available?domain=${encodeURIComponent(domain)}`
    );
  }

  async bulkCheckAvailability(domains: string[]) {
    return this.request<unknown>("POST", "/v2/domains/available", domains);
  }

  // ── Registration ─────────────────────────────────────────────────────────

  async validateRegistration(registration: DomainRegistration) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/register/validate`,
      registration
    );
  }

  async registerDomain(registration: DomainRegistration) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/register`,
      registration
    );
  }

  async getRegistrationSchema(tld: string) {
    return this.request<unknown>(
      "GET",
      `/v2/customers/${this.customerId}/domains/register/schema/${tld}`
    );
  }

  // ── Renewal ───────────────────────────────────────────────────────────────

  async renewDomain(domain: string, period?: number) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/${domain}/renew`,
      period ? { period } : {}
    );
  }

  // ── Transfer ──────────────────────────────────────────────────────────────

  async checkTransferAvailability(domain: string) {
    return this.request<unknown>("POST", "/v2/domains/transferAvailable", { domain });
  }

  async transferDomain(domain: string, authCode: string, period?: number) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/${domain}/transfer`,
      { authCode, ...(period ? { period } : {}) }
    );
  }

  async cancelTransfer(domain: string) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/${domain}/transferInCancel`
    );
  }

  // ── Nameservers ───────────────────────────────────────────────────────────

  async updateNameServers(domain: string, nameServers: string[]) {
    return this.request<unknown>(
      "PUT",
      `/v2/customers/${this.customerId}/domains/${domain}/nameServers`,
      nameServers
    );
  }

  // ── Contacts ─────────────────────────────────────────────────────────────

  async updateContacts(domain: string, contacts: DomainContacts) {
    return this.request<unknown>(
      "PATCH",
      `/v2/customers/${this.customerId}/domains/${domain}/contacts`,
      contacts
    );
  }

  async getContactSchema(tld: string) {
    return this.request<unknown>(
      "GET",
      `/v2/customers/${this.customerId}/domains/contacts/schema/${tld}`
    );
  }

  // ── Privacy ───────────────────────────────────────────────────────────────

  async enablePrivacy(domain: string) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/${domain}/privacy/purchase`
    );
  }

  async disablePrivacy(domain: string) {
    return this.request<unknown>(
      "DELETE",
      `/v2/customers/${this.customerId}/domains/${domain}/privacy`
    );
  }

  // ── DNS ───────────────────────────────────────────────────────────────────

  async getDnsRecords(domain: string, type?: string, name?: string) {
    let path = `/v2/customers/${this.customerId}/domains/${domain}/dns/records`;
    if (type) path += `/${type}`;
    if (type && name) path += `/${encodeURIComponent(name)}`;
    return this.request<unknown[]>("GET", path);
  }

  async addDnsRecords(domain: string, records: DnsRecord[]) {
    return this.request<unknown>(
      "PATCH",
      `/v2/customers/${this.customerId}/domains/${domain}/dns/records`,
      records
    );
  }

  async replaceDnsRecords(domain: string, type: string, name: string, records: DnsRecord[]) {
    return this.request<unknown>(
      "PUT",
      `/v2/customers/${this.customerId}/domains/${domain}/dns/records/${type}/${encodeURIComponent(name)}`,
      records
    );
  }

  async deleteDnsRecords(domain: string, type: string, name: string) {
    return this.request<unknown>(
      "DELETE",
      `/v2/customers/${this.customerId}/domains/${domain}/dns/records/${type}/${encodeURIComponent(name)}`
    );
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async getDomainActions(domain: string) {
    return this.request<unknown[]>(
      "GET",
      `/v2/customers/${this.customerId}/domains/${domain}/actions`
    );
  }

  async getDomainAction(domain: string, type: string) {
    return this.request<Record<string, unknown>>(
      "GET",
      `/v2/customers/${this.customerId}/domains/${domain}/actions/${type}`
    );
  }

  async cancelDomainAction(domain: string, type: string) {
    return this.request<unknown>(
      "DELETE",
      `/v2/customers/${this.customerId}/domains/${domain}/actions/${type}`
    );
  }

  // ── Auth Code ─────────────────────────────────────────────────────────────

  async regenerateAuthCode(domain: string) {
    return this.request<unknown>(
      "POST",
      `/v2/customers/${this.customerId}/domains/${domain}/regenerateAuthCode`
    );
  }
}
