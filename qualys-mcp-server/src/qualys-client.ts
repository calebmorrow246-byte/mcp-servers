import axios, { type AxiosInstance, AxiosError } from "axios";
import https from "node:https";
import { XMLParser } from "fast-xml-parser";

export interface QualysConfig {
  baseUrl: string;
  username: string;
  password: string;
  insecure?: boolean;
  /**
   * Knowledge Base API version. Qualys deprecated v2.0 of the Knowledge Base
   * API (March 2025) on many platforms in favour of v3.0. Default is "2.0";
   * set QUALYS_KB_VERSION=3.0 if your subscription returns a deprecation error.
   */
  kbVersion?: string;
}

// ---- Normalized result shapes -------------------------------------------------

export interface HostDetection {
  ip: string;
  dns: string;
  os: string;
  tags: string;
  qid: string;
  type: string;
  severity: string;
  status: string;
  firstFound: string;
  lastFound: string;
  results: string;
  /** Instance-defining fields; a multi-instance QID yields one detection per port/service. Empty when Qualys omits them. */
  uniqueVulnId: string;
  port: string;
  protocol: string;
  fqdn: string;
  ssl: string;
  instance: string;
  /** Azure instance metadata attributes (name, value); empty unless includeCloudMetadata was set. */
  azure: Record<string, string>;
}

/** Common tag-based host selection options (Qualys FO asset-tag parameters). */
export interface TagFilter {
  /** Comma-separated tag names (default) or IDs — set tagsBy accordingly. */
  tags?: string;
  /** How to interpret tags: match "any" (default) or "all" of them. */
  tagsMatch?: "any" | "all";
  /** Whether `tags` are specified by "name" (default) or "id". */
  tagsBy?: "name" | "id";
}

export interface QualysTag {
  id: string;
  name: string;
  parentId: string;
  criticality: string;
}

export interface VulnInfo {
  qid: string;
  title: string;
  severity: string;
  category: string;
  cveIds: string;
  patchable: string;
  published: string;
  diagnosis: string;
  solution: string;
}

export interface ScanInfo {
  ref: string;
  title: string;
  status: string;
  launchDate: string;
  duration: string;
  target: string;
  type: string;
}

export interface HostAsset {
  id: string;
  ip: string;
  dns: string;
  netbios: string;
  os: string;
  tags: string;
  tracking: string;
  lastScan: string;
  lastVulnScan: string;
  /** Azure instance metadata attributes (name, value); empty unless includeCloudMetadata was set. */
  azure: Record<string, string>;
}

export interface WebApp {
  id: string;
  name: string;
  url: string;
  owner: string;
  createdDate: string;
  updatedDate: string;
}

export interface WasFinding {
  id: string;
  qid: string;
  name: string;
  type: string;
  severity: string;
  status: string;
  url: string;
  firstDetected: string;
  lastDetected: string;
}

// ---- Helpers ------------------------------------------------------------------

/** Coerce fast-xml-parser output (which collapses single-item lists to an object) into an array. */
function toArray<T>(value: T | T[] | undefined | null): T[] {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

function str(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") {
    // fast-xml-parser wraps CDATA / attributed nodes; fall back to #text.
    const t = (value as Record<string, unknown>)["#text"];
    return t === undefined ? "" : String(t);
  }
  return String(value);
}

export class QualysClient {
  private http: AxiosInstance;
  private parser: XMLParser;
  private kbVersion: string;

  constructor(config: QualysConfig) {
    this.kbVersion = config.kbVersion || "2.0";
    const baseURL = config.baseUrl.replace(/\/+$/, "");

    this.http = axios.create({
      baseURL,
      timeout: 120_000, // Qualys list operations can be slow on large subscriptions.
      auth: { username: config.username, password: config.password },
      headers: {
        // Required on every Qualys API call — the value is arbitrary but must be present.
        "X-Requested-With": "qualys-mcp-server",
      },
      httpsAgent: new https.Agent({ rejectUnauthorized: !config.insecure }),
      // We handle non-2xx ourselves to surface Qualys' XML error text.
      validateStatus: () => true,
    });

    this.parser = new XMLParser({
      ignoreAttributes: false,
      attributeNamePrefix: "@_",
      trimValues: true,
      // Every &amp;/&lt;/... counts as an entity expansion. The default cap (1000 per document) is
      // exceeded by real responses such as list_tags, so raise the totals while keeping them bounded;
      // the shallow depth limit still blocks recursive ("billion laughs") expansion.
      processEntities: {
        enabled: true,
        maxTotalExpansions: 100_000,
        maxExpandedLength: 10_000_000,
        maxExpansionDepth: 10,
      },
    });
  }

  // ---- Core request plumbing --------------------------------------------------

  /** Classic Qualys "FO" API (VMDR / assets / scans). Form-encoded, XML response. */
  private async foRequest(path: string, params: Record<string, string | undefined>): Promise<any> {
    const form = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") form.append(k, v);
    }

    const res = await this.http.post(path, form.toString(), {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });

    const parsed = this.parser.parse(typeof res.data === "string" ? res.data : String(res.data));

    // Qualys signals errors via <SIMPLE_RETURN> or an HTTP status with a CODE/TEXT.
    const simple = parsed?.SIMPLE_RETURN?.RESPONSE;
    if (simple && simple.CODE) {
      throw new Error(`Qualys error ${str(simple.CODE)}: ${str(simple.TEXT)}`);
    }
    if (res.status >= 400) {
      throw new Error(`Qualys HTTP ${res.status}: ${typeof res.data === "string" ? res.data.slice(0, 500) : res.statusText}`);
    }
    return parsed;
  }

  /** QPS REST API (WAS). Takes an XML ServiceRequest body, returns XML ServiceResponse. */
  private async qpsRequest(path: string, serviceRequestXml: string): Promise<any> {
    const res = await this.http.post(path, serviceRequestXml, {
      // Force XML: the QPS/WAS API honours Accept and would otherwise return JSON
      // (axios sends application/json by default), which axios auto-parses to an
      // object and breaks XML parsing. The FO API ignores Accept and is unaffected.
      headers: { "Content-Type": "text/xml", Accept: "application/xml" },
    });

    // Defensive: if a JSON object still comes back, use it directly.
    const parsed = typeof res.data === "object" && res.data !== null
      ? res.data
      : this.parser.parse(String(res.data));
    const sr = parsed?.ServiceResponse;

    if (sr?.responseCode && str(sr.responseCode) !== "SUCCESS") {
      const detail = str(sr.responseErrorDetails?.errorMessage) || str(sr.responseCode);
      throw new Error(`Qualys WAS error: ${detail}`);
    }
    if (res.status >= 400) {
      throw new Error(`Qualys HTTP ${res.status}: ${typeof res.data === "string" ? res.data.slice(0, 500) : res.statusText}`);
    }
    return parsed;
  }

  /**
   * Translate a TagFilter into Qualys FO asset-tag parameters. When tags are
   * supplied, host selection switches to tag mode (use_tags=1) and any IP filter
   * is ignored by Qualys, so callers should treat tags and ips as alternatives.
   */
  private tagParams(f: TagFilter): Record<string, string | undefined> {
    if (!f.tags) return {};
    return {
      use_tags: "1",
      tag_set_by: f.tagsBy ?? "name",
      tag_set_include: f.tags,
      tag_include_selector: f.tagsMatch ?? "any",
    };
  }

  /** Extract asset-tag names from a HOST node (present when show_tags=1). */
  private hostTags(host: any): string {
    return toArray<any>(host?.TAGS?.TAG)
      .map((t) => str(t.NAME) || str(t.TAG_ID))
      .filter(Boolean)
      .join(", ");
  }

  /**
   * Extract Azure instance metadata from a HOST node (present when host_metadata=azure
   * and an Azure connector has synced the instance). Returns attribute name -> value.
   */
  private hostAzureMetadata(host: any): Record<string, string> {
    const out: Record<string, string> = {};
    for (const attr of toArray<any>(host?.METADATA?.AZURE?.ATTRIBUTE)) {
      const name = str(attr.NAME);
      const value = str(attr.VALUE);
      if (name && value) out[name] = value;
    }
    return out;
  }

  private buildWasServiceRequest(
    criteria: Array<{ field: string; operator: string; value: string }>,
    limit: number
  ): string {
    const filters = criteria
      .map((c) => `<Criteria field="${c.field}" operator="${c.operator}">${escapeXml(c.value)}</Criteria>`)
      .join("");
    return (
      `<ServiceRequest>` +
      `<preferences><limitResults>${limit}</limitResults></preferences>` +
      (filters ? `<filters>${filters}</filters>` : "") +
      `</ServiceRequest>`
    );
  }

  // ---- VMDR -------------------------------------------------------------------

  async listHostDetections(opts: {
    ips?: string;
    severities?: string;
    qids?: string;
    status?: string;
    showIgs?: boolean;
    includeResults?: boolean;
    includeCloudMetadata?: boolean;
    truncationLimit?: number;
  } & TagFilter): Promise<HostDetection[]> {
    const parsed = await this.foRequest("/api/2.0/fo/asset/host/vm/detection/", {
      action: "list",
      // Tags and ips are alternative selection methods; tags win when present.
      ...(opts.tags ? {} : { ips: opts.ips }),
      ...this.tagParams(opts),
      show_tags: "1",
      severities: opts.severities,
      qids: opts.qids,
      status: opts.status,
      show_igs: opts.showIgs ? "1" : "0",
      ...(opts.includeResults ? { show_results: "1" } : {}),
      ...(opts.includeCloudMetadata ? { host_metadata: "azure" } : {}),
      truncation_limit: String(opts.truncationLimit ?? 500),
    });

    const hosts = toArray<any>(parsed?.HOST_LIST_VM_DETECTION_OUTPUT?.RESPONSE?.HOST_LIST?.HOST);
    const out: HostDetection[] = [];
    for (const h of hosts) {
      const detections = toArray<any>(h?.DETECTION_LIST?.DETECTION);
      for (const d of detections) {
        out.push({
          ip: str(h.IP),
          dns: str(h.DNS),
          os: str(h.OS),
          tags: this.hostTags(h),
          qid: str(d.QID),
          type: str(d.TYPE),
          severity: str(d.SEVERITY),
          status: str(d.STATUS),
          firstFound: str(d.FIRST_FOUND_DATETIME),
          lastFound: str(d.LAST_FOUND_DATETIME),
          results: str(d.RESULTS),
          uniqueVulnId: str(d.UNIQUE_VULN_ID),
          port: str(d.PORT),
          protocol: str(d.PROTOCOL),
          fqdn: str(d.FQDN),
          ssl: str(d.SSL),
          instance: str(d.INSTANCE),
          azure: this.hostAzureMetadata(h),
        });
      }
    }
    return out;
  }

  async getVulnerabilityInfo(opts: { ids?: string; cveIds?: string }): Promise<VulnInfo[]> {
    const parsed = await this.foRequest(`/api/${this.kbVersion}/fo/knowledge_base/vuln/`, {
      action: "list",
      ids: opts.ids,
      cve_ids: opts.cveIds,
      details: "All",
    });

    const vulns = toArray<any>(parsed?.KNOWLEDGE_BASE_VULN_LIST_OUTPUT?.RESPONSE?.VULN_LIST?.VULN);
    return vulns.map((v) => {
      const cves = toArray<any>(v?.CVE_LIST?.CVE).map((c) => str(c.ID)).join(", ");
      return {
        qid: str(v.QID),
        title: str(v.TITLE),
        severity: str(v.SEVERITY_LEVEL),
        category: str(v.CATEGORY),
        cveIds: cves,
        patchable: str(v.PATCHABLE),
        published: str(v.PUBLISHED_DATETIME),
        diagnosis: str(v.DIAGNOSIS),
        solution: str(v.SOLUTION),
      };
    });
  }

  async listScans(opts: { state?: string; scanRef?: string }): Promise<ScanInfo[]> {
    const parsed = await this.foRequest("/api/2.0/fo/scan/", {
      action: "list",
      state: opts.state,
      scan_ref: opts.scanRef,
    });

    const scans = toArray<any>(parsed?.SCAN_LIST_OUTPUT?.RESPONSE?.SCAN_LIST?.SCAN);
    return scans.map((s) => ({
      ref: str(s.REF),
      title: str(s.TITLE),
      status: str(s.STATUS?.STATE) || str(s.STATUS),
      launchDate: str(s.LAUNCH_DATETIME),
      duration: str(s.DURATION),
      target: str(s.TARGET),
      type: str(s.TYPE),
    }));
  }

  // ---- Asset inventory (classic Host List API) --------------------------------

  async listHostAssets(
    opts: { ips?: string; includeCloudMetadata?: boolean; truncationLimit?: number } & TagFilter
  ): Promise<HostAsset[]> {
    const parsed = await this.foRequest("/api/2.0/fo/asset/host/", {
      action: "list",
      ...(opts.tags ? {} : { ips: opts.ips }),
      ...this.tagParams(opts),
      show_tags: "1",
      ...(opts.includeCloudMetadata ? { host_metadata: "azure" } : {}),
      truncation_limit: String(opts.truncationLimit ?? 500),
    });

    const hosts = toArray<any>(parsed?.HOST_LIST_OUTPUT?.RESPONSE?.HOST_LIST?.HOST);
    return hosts.map((h) => ({
      id: str(h.ID),
      ip: str(h.IP),
      dns: str(h.DNS),
      netbios: str(h.NETBIOS),
      os: str(h.OS),
      tags: this.hostTags(h),
      tracking: str(h.TRACKING_METHOD),
      lastScan: str(h.LAST_SCAN_DATETIME),
      lastVulnScan: str(h.LAST_VULN_SCAN_DATETIME),
      azure: this.hostAzureMetadata(h),
    }));
  }

  // ---- Tags (Asset Management & Tagging) --------------------------------------

  async listTags(opts: { nameContains?: string; limit?: number }): Promise<QualysTag[]> {
    const criteria = opts.nameContains
      ? [{ field: "name", operator: "CONTAINS", value: opts.nameContains }]
      : [];
    const body = this.buildWasServiceRequest(criteria, opts.limit ?? 200);
    const parsed = await this.qpsRequest("/qps/rest/2.0/search/am/tag", body);

    const tags = toArray<any>(parsed?.ServiceResponse?.data?.Tag);
    return tags.map((t) => ({
      id: str(t.id),
      name: str(t.name),
      parentId: str(t.parentTagId),
      criticality: str(t.criticalityScore),
    }));
  }

  // ---- WAS --------------------------------------------------------------------

  async listWebApps(opts: { nameContains?: string; limit?: number }): Promise<WebApp[]> {
    const criteria = opts.nameContains
      ? [{ field: "name", operator: "CONTAINS", value: opts.nameContains }]
      : [];
    const body = this.buildWasServiceRequest(criteria, opts.limit ?? 100);
    const parsed = await this.qpsRequest("/qps/rest/3.0/search/was/webapp", body);

    const apps = toArray<any>(parsed?.ServiceResponse?.data?.WebApp);
    return apps.map((w) => ({
      id: str(w.id),
      name: str(w.name),
      url: str(w.url),
      owner: str(w.owner?.username) || str(w.owner),
      createdDate: str(w.createdDate),
      updatedDate: str(w.updatedDate),
    }));
  }

  async listWasFindings(opts: {
    webAppId?: string;
    severity?: string;
    status?: string;
    limit?: number;
  }): Promise<WasFinding[]> {
    const criteria: Array<{ field: string; operator: string; value: string }> = [];
    if (opts.webAppId) criteria.push({ field: "webApp.id", operator: "EQUALS", value: opts.webAppId });
    if (opts.severity) criteria.push({ field: "severity", operator: "EQUALS", value: opts.severity });
    if (opts.status) criteria.push({ field: "status", operator: "EQUALS", value: opts.status });

    const body = this.buildWasServiceRequest(criteria, opts.limit ?? 100);
    const parsed = await this.qpsRequest("/qps/rest/3.0/search/was/finding", body);

    const findings = toArray<any>(parsed?.ServiceResponse?.data?.Finding);
    return findings.map((f) => ({
      id: str(f.id),
      qid: str(f.qid),
      name: str(f.name),
      type: str(f.type),
      severity: str(f.severity),
      status: str(f.status),
      url: str(f.url),
      firstDetected: str(f.firstDetectedDate),
      lastDetected: str(f.lastDetectedDate),
    }));
  }
}

function escapeXml(v: string): string {
  return v
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Re-export for callers that want to distinguish transport errors.
export { AxiosError };
