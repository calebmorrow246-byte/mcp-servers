import axios, { type AxiosInstance, AxiosError } from "axios";

export interface ValimailConfig {
  baseUrl: string;
  clientId: string;
  appId: string;
  accountSlug: string;
  insecure?: boolean;
}

// ---- Config API shapes ---------------------------------------------------

export interface Domain {
  domain: string;
  "is-org-domain"?: boolean;
  "dmarc-record-type"?: string;
  "dmarc-record"?: string;
  "enforcement-status"?: string;
  "dmarc-policy"?: string;
  "sending-status"?: string;
  "account-slug"?: string;
  "last-report-date"?: string;
  "dmarc-pcd"?: string;
}

export interface Sender {
  slug: string;
  name?: string;
  status?: string;
  domainSlug?: string;
  accountSlug?: string;
}

export interface SenderProvider {
  slug: string;
  name?: string;
}

export interface Dkim {
  selector: string;
  "public-key"?: string;
  "cname-target"?: string;
  comment?: string;
  "sender-slug"?: string;
  "sender-owner"?: string;
  "domain-owner"?: string;
}

export interface Netblock {
  netblock: string;
  "spf-record"?: string;
  comment?: string;
  "sender-slug"?: string;
  "domain-slug"?: string;
}

// ---- Reporting API shapes -------------------------------------------------

export interface SendersReportRow {
  service_name: string;
  service_status: string;
  total_messages_count: number;
  passing_percentage: number;
  dmarc_passing_count: number;
  dmarc_failing_count: number;
  allowed_through_no_enforcement_count: number;
  allowed_through_with_enforcement_count: number;
  aligned_spf_count: number;
  failing_or_unaligned_spf_count: number;
  dmarc_overridden_count: number;
  quarantined_count: number;
  rejected_count: number;
}

export interface UnidentifiedReportRow {
  "ptr-name": string;
  "source-ip": string;
  "geo-country-code": string;
  "spf-domain": string;
  "dmarc-policy-org-domain": string;
  "passing-percentage": number;
  "total-messages-count": number;
  "dmarc-passing-count": number;
  "dmarc-failing-count": number;
  "allowed-through-no-enforcement-count": number;
  "allowed-through-with-enforcement-count": number;
  "aligned-spf-count": number;
  "failing-spf-count": number;
  "unaligned-spf-count": number;
  "dmarc-overridden-count": number;
  "quarantined-count": number;
  "rejected-count": number;
}

export interface EventRow {
  subject: string;
  user: string;
  "event-type": string;
  "event-change": string;
  "performed-at": string;
}

export interface DkimContinuousProtectionRow {
  "sender-name": string;
  "domain-name": string;
  "dkim-selector": string;
  "dkim-type": string;
  "dkim-bits": number;
  "uploaded-date": string;
  "last-seen-date": string;
  "sender-owner": string;
  "domain-owner": string;
  comment: string;
}

export interface SenderContinuousProtectionRow {
  "sender-name": string;
  "domain-name": string;
  "last-seen-date": string;
  "email-volume": string;
  notes: string;
}

export interface TlsReportRow {
  domain: string;
  "report-id": string;
  version: string;
  "policy-mode": string;
  "policy-mx-host": string;
  "max-age": number;
}

export interface TlsReportResult {
  count: number;
  next?: string;
  previous?: string;
  rows: TlsReportRow[];
}

export interface TlsFailureDetailRow {
  domain_name: string;
  report_id: string;
  sending_mta_ip: string;
  start_date: string;
  end_date: string;
  receiving_ip: string;
  receiving_mx_host_name: string;
  success_count: number;
  failure_count: number;
}

// ---- Client ----------------------------------------------------------------

interface TokenCache {
  token: string;
  expiresAtMs: number;
}

/** Serialize query params the way Valimail's OpenAPI specs expect: repeated
 * `key=value` pairs for arrays (no `[]` suffix), booleans as "true"/"false". */
function serializeParams(params: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      if (v === undefined || v === null || v === "") continue;
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`);
    }
  }
  return parts.join("&");
}

function normalizeError(err: unknown): Error {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as Record<string, unknown> | undefined;
    if (data) {
      const message = data.message as string | undefined;
      if (message) return new Error(`Valimail API error (HTTP ${err.response?.status}): ${message}`);

      const details = (data.detail ?? data.details) as
        | Array<{ field?: string; message?: string }>
        | undefined;
      if (details && details.length > 0) {
        const msg = details.map((d) => `${d.field ?? "field"}: ${d.message ?? "invalid"}`).join("; ");
        return new Error(`Valimail API validation error (HTTP ${err.response?.status}): ${msg}`);
      }
    }
    return new Error(`Valimail API error (HTTP ${err.response?.status ?? "?"}): ${err.message}`);
  }
  return err instanceof Error ? err : new Error(String(err));
}

export class ValimailClient {
  private http: AxiosInstance;
  private clientId: string;
  private appId: string;
  private accountSlug: string;
  private tokenCache?: TokenCache;

  constructor(config: ValimailConfig) {
    this.clientId = config.clientId;
    this.appId = config.appId;
    this.accountSlug = config.accountSlug;
    const baseURL = config.baseUrl.replace(/\/+$/, "");

    this.http = axios.create({
      baseURL,
      timeout: 30_000,
      paramsSerializer: { serialize: serializeParams },
    });
  }

  // ---- Auth ------------------------------------------------------------------

  private async getToken(): Promise<string> {
    const now = Date.now();
    // Refresh a minute before expiry to avoid racing a token that dies mid-request.
    if (this.tokenCache && this.tokenCache.expiresAtMs - 60_000 > now) {
      return this.tokenCache.token;
    }

    const res = await this.http.post<{ token: string; "expires-at": string }>("/auth", {
      "client-id": this.clientId,
      "app-id": this.appId,
    });

    const expiresAtMs = Date.parse(res.data["expires-at"]);
    this.tokenCache = {
      token: res.data.token,
      expiresAtMs: Number.isNaN(expiresAtMs) ? now + 15 * 60_000 : expiresAtMs,
    };
    return this.tokenCache.token;
  }

  private async request<T>(
    method: "get" | "post" | "put" | "delete",
    path: string,
    opts: { params?: Record<string, unknown>; data?: unknown } = {}
  ): Promise<T> {
    const token = await this.getToken();
    try {
      const res = await this.http.request<T>({
        method,
        url: path,
        params: opts.params,
        data: opts.data,
        headers: { Authorization: `Bearer ${token}` },
      });
      return res.data;
    } catch (err) {
      throw normalizeError(err);
    }
  }

  private acctPath(suffix: string): string {
    return `/accounts/${encodeURIComponent(this.accountSlug)}${suffix}`;
  }

  // ---- Domains (Config) --------------------------------------------------

  async listDomains(filters: {
    domain?: string[];
    dmarcRecord?: string[];
    enforcementStatus?: string[];
    dmarcPolicy?: string[];
    sendingStatus?: string[];
    orgDomainOnly?: boolean;
    reverse?: boolean;
    sortKey?: string;
  } = {}): Promise<Domain[]> {
    return this.request<Domain[]>("get", this.acctPath("/domains"), {
      params: {
        domain: filters.domain,
        "dmarc-record": filters.dmarcRecord,
        "enforcement-status": filters.enforcementStatus,
        "dmarc-policy": filters.dmarcPolicy,
        "sending-status": filters.sendingStatus,
        "org-domain-only": filters.orgDomainOnly,
        reverse: filters.reverse,
        "sort-key": filters.sortKey,
      },
    });
  }

  async getDomain(domain: string): Promise<Domain> {
    return this.request<Domain>("get", this.acctPath(`/domains/${encodeURIComponent(domain)}`));
  }

  async createDomain(domain: string): Promise<Domain> {
    return this.request<Domain>("post", this.acctPath("/domains"), { data: { domain } });
  }

  async updateDomain(
    domain: string,
    updates: { dmarcPolicy?: string; sendingStatus?: string }
  ): Promise<Domain> {
    return this.request<Domain>("put", this.acctPath(`/domains/${encodeURIComponent(domain)}`), {
      data: {
        "dmarc-policy": updates.dmarcPolicy,
        "sending-status": updates.sendingStatus,
      },
    });
  }

  async deleteDomain(domain: string): Promise<Domain> {
    return this.request<Domain>("delete", this.acctPath(`/domains/${encodeURIComponent(domain)}`));
  }

  // ---- Senders (Config) ---------------------------------------------------

  async listSenders(domain: string): Promise<Sender[]> {
    return this.request<Sender[]>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/senders`)
    );
  }

  async getSender(domain: string, senderSlug: string): Promise<Sender> {
    return this.request<Sender>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/senders/${encodeURIComponent(senderSlug)}`)
    );
  }

  async createSender(domain: string, senderSlug: string): Promise<Sender> {
    return this.request<Sender>(
      "post",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/senders`),
      { data: { Slug: senderSlug } }
    );
  }

  async updateSenderStatus(
    domain: string,
    senderSlug: string,
    status: "approved" | "denied" | "pending_approval"
  ): Promise<Sender> {
    return this.request<Sender>(
      "put",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/senders/${encodeURIComponent(senderSlug)}`),
      { data: { Status: status } }
    );
  }

  async listAvailableSenders(): Promise<SenderProvider[]> {
    return this.request<SenderProvider[]>("get", "/resource/senders");
  }

  // ---- DKIM by domain (Config) ---------------------------------------------

  async listDomainDkims(domain: string, reverse?: boolean): Promise<Dkim[]> {
    return this.request<Dkim[]>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/dkims`),
      { params: { reverse } }
    );
  }

  async getDomainDkim(domain: string, selector: string): Promise<Dkim> {
    return this.request<Dkim>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/dkims/${encodeURIComponent(selector)}`)
    );
  }

  async createDomainDkim(
    domain: string,
    body: {
      selector: string;
      publicKey?: string;
      cnameTarget?: string;
      comment?: string;
      exactDomainOnly?: boolean;
      shortKeyOverride?: boolean;
      skipVersionTag?: boolean;
      skipKeyTag?: boolean;
    }
  ): Promise<Dkim> {
    return this.request<Dkim>(
      "post",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/dkims`),
      {
        data: {
          Selector: body.selector,
          PublicKey: body.publicKey,
          CnameTarget: body.cnameTarget,
          Comment: body.comment,
          ExactDomainOnly: body.exactDomainOnly,
          ShortKeyOverride: body.shortKeyOverride,
          SkipVersionTag: body.skipVersionTag,
          SkipKeyTag: body.skipKeyTag,
        },
      }
    );
  }

  async updateDomainDkim(
    domain: string,
    selector: string,
    updates: {
      newSenderSlug?: string;
      comment?: string;
      senderOwner?: string;
      domainOwner?: string;
    }
  ): Promise<Dkim> {
    return this.request<Dkim>(
      "put",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/dkims/${encodeURIComponent(selector)}`),
      {
        data: {
          "new-sender-slug": updates.newSenderSlug,
          comment: updates.comment,
          "sender-owner": updates.senderOwner,
          "domain-owner": updates.domainOwner,
        },
      }
    );
  }

  // ---- Netblocks (Config) ---------------------------------------------------

  async listNetblocks(domain: string, reverse?: boolean): Promise<Netblock[]> {
    return this.request<Netblock[]>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/netblocks`),
      { params: { reverse } }
    );
  }

  async getNetblock(domain: string, netblock: string): Promise<Netblock> {
    return this.request<Netblock>(
      "get",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/netblocks/${encodeURIComponent(netblock)}`)
    );
  }

  async createNetblock(
    domain: string,
    body: { netblock: string; comment?: string; senderSlug?: string }
  ): Promise<Netblock> {
    return this.request<Netblock>(
      "post",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/netblocks`),
      { data: { netblock: body.netblock, comment: body.comment, "sender-slug": body.senderSlug } }
    );
  }

  async updateNetblock(
    domain: string,
    netblock: string,
    updates: { comment?: string; senderSlug?: string }
  ): Promise<Netblock> {
    return this.request<Netblock>(
      "put",
      this.acctPath(`/domains/${encodeURIComponent(domain)}/netblocks/${encodeURIComponent(netblock)}`),
      { data: { comment: updates.comment, "sender-slug": updates.senderSlug } }
    );
  }

  // ---- Reporting: Domains ----------------------------------------------------

  async getDomainsReport(filters: {
    domain?: string[];
    dmarcRecord?: string[];
    enforcementStatus?: string[];
    dmarcPolicy?: string[];
    sendingStatus?: string[];
    orgDomainOnly?: boolean;
    reverse?: boolean;
    sortKey?: string;
  } = {}): Promise<Domain[]> {
    return this.request<Domain[]>("get", this.acctPath("/reports/domains"), {
      params: {
        domain: filters.domain,
        "dmarc-record": filters.dmarcRecord,
        "enforcement-status": filters.enforcementStatus,
        "dmarc-policy": filters.dmarcPolicy,
        "sending-status": filters.sendingStatus,
        "org-domain-only": filters.orgDomainOnly,
        reverse: filters.reverse,
        "sort-key": filters.sortKey,
      },
    });
  }

  // ---- Reporting: Senders / Unidentified -------------------------------------

  async getSendersReport(params: {
    domains: string[];
    startDate: string;
    endDate: string;
    reverse?: boolean;
    page?: number;
    perPage?: number;
  }): Promise<SendersReportRow[]> {
    return this.request<SendersReportRow[]>("get", this.acctPath("/reports/senders"), {
      params: {
        domains: params.domains,
        "start-date": params.startDate,
        "end-date": params.endDate,
        reverse: params.reverse,
        page: params.page,
        "per-page": params.perPage,
      },
    });
  }

  async getUnidentifiedReport(params: {
    domains: string[];
    startDate: string;
    endDate: string;
    reverse?: boolean;
    page?: number;
    perPage?: number;
  }): Promise<UnidentifiedReportRow[]> {
    return this.request<UnidentifiedReportRow[]>("get", this.acctPath("/reports/unidentified"), {
      params: {
        domains: params.domains,
        "start-date": params.startDate,
        "end-date": params.endDate,
        reverse: params.reverse,
        page: params.page,
        "per-page": params.perPage,
      },
    });
  }

  // ---- Reporting: Events ------------------------------------------------------

  async getEventsReport(params: {
    subjects?: string[];
    userId?: string;
    eventType?: string;
    startDate: string;
    endDate: string;
    reverse?: boolean;
    page?: number;
    perPage?: number;
  }): Promise<EventRow[]> {
    return this.request<EventRow[]>("get", this.acctPath("/reports/events"), {
      params: {
        subjects: params.subjects,
        "user-id": params.userId,
        "event-type": params.eventType,
        "start-date": params.startDate,
        "end-date": params.endDate,
        reverse: params.reverse,
        page: params.page,
        "per-page": params.perPage,
      },
    });
  }

  // ---- Reporting: Continuous Protection ---------------------------------------

  async getDkimContinuousProtectionReport(params: {
    senderName?: string;
    domainName?: string;
    uploadedStartDate?: string;
    uploadedEndDate?: string;
    lastSeenStartDate?: string;
    lastSeenEndDate?: string;
    sortKey?: string;
    reverse?: boolean;
    page?: number;
    perPage?: number;
  } = {}): Promise<DkimContinuousProtectionRow[]> {
    return this.request<DkimContinuousProtectionRow[]>(
      "get",
      this.acctPath("/reports/continuous-protection/dkim"),
      {
        params: {
          "sender-name": params.senderName,
          "domain-name": params.domainName,
          "uploaded-start-date": params.uploadedStartDate,
          "uploaded-end-date": params.uploadedEndDate,
          "last-seen-start-date": params.lastSeenStartDate,
          "last-seen-end-date": params.lastSeenEndDate,
          "sort-key": params.sortKey,
          reverse: params.reverse,
          page: params.page,
          "per-page": params.perPage,
        },
      }
    );
  }

  async getSendersContinuousProtectionReport(params: {
    senderName?: string;
    domainName?: string;
    lastSeenStartDate?: string;
    lastSeenEndDate?: string;
    sortKey?: string;
    reverse?: boolean;
    page?: number;
    perPage?: number;
  } = {}): Promise<SenderContinuousProtectionRow[]> {
    return this.request<SenderContinuousProtectionRow[]>(
      "get",
      this.acctPath("/reports/continuous-protection/senders"),
      {
        params: {
          "sender-name": params.senderName,
          "domain-name": params.domainName,
          "last-seen-start-date": params.lastSeenStartDate,
          "last-seen-end-date": params.lastSeenEndDate,
          "sort-key": params.sortKey,
          reverse: params.reverse,
          page: params.page,
          "per-page": params.perPage,
        },
      }
    );
  }

  // ---- Reporting: MTA-STS / TLS ------------------------------------------------

  async getTlsReport(params: {
    startDate: string;
    endDate: string;
    domainNames?: string[];
    policyMxHost?: string;
    policyMode?: "none" | "enforce" | "testing" | "unknown";
    limit?: number;
    page?: number;
    sort?: string;
  }): Promise<TlsReportResult> {
    const data = await this.request<{
      Count: number;
      Next?: string;
      Previous?: string;
      Results: TlsReportRow[];
    }>("get", this.acctPath("/reports/mta-sts/tls"), {
      params: {
        "start-date": params.startDate,
        "end-date": params.endDate,
        "domain-names": params.domainNames,
        "policy-mx-host": params.policyMxHost,
        "policy-mode": params.policyMode,
        limit: params.limit,
        page: params.page,
        sort: params.sort,
      },
    });
    return { count: data.Count, next: data.Next, previous: data.Previous, rows: data.Results ?? [] };
  }

  async getTlsFailureDetails(params: {
    reportId: string;
    domainName: string;
    policyMode?: "none" | "enforce" | "testing" | "unknown";
    policyType?: "no-policy-found" | "tlsa" | "sts";
  }): Promise<TlsFailureDetailRow[]> {
    return this.request<TlsFailureDetailRow[]>(
      "get",
      this.acctPath("/reports/mta-sts/tls/failure-details"),
      {
        params: {
          "report-id": params.reportId,
          "domain-name": params.domainName,
          "policy-mode": params.policyMode,
          "policy-type": params.policyType,
        },
      }
    );
  }
}

export { AxiosError };
