import axios, { type AxiosInstance } from "axios";
import https from "node:https";

export interface PhpIPAMConfig {
  baseUrl: string;
  appId: string;
  username?: string;
  password?: string;
  /** Static app token for phpIPAM "App token" security mode — skips the /user/ login. */
  appToken?: string;
  insecure?: boolean;
}

interface ApiResponse<T = unknown> {
  success: boolean;
  code: number;
  message?: string;
  data?: T;
  id?: string | number;
}

export interface Section {
  id: string;
  name: string;
  description: string | null;
  masterSection: string;
  permissions: string;
}

export interface Subnet {
  id: string;
  subnet: string;
  mask: string;
  description: string | null;
  sectionId: string;
  vlanId: string | null;
  vrfId: string | null;
  masterSubnetId: string;
  nameserverId: string | null;
  showName: string;
  isFolder: string;
  isFull: string;
  tag: string;
  location: string | null;
}

export interface SubnetUsage {
  used: number;
  maxhosts: number;
  freehosts: number;
  freehosts_percent: number;
  Offline_percent: number;
  Used_percent: number;
  reserved_percent: number;
  dhcp_percent: number;
}

export interface Address {
  id: string;
  subnetId: string;
  ip: string;
  is_gateway: string;
  description: string | null;
  hostname: string | null;
  mac: string | null;
  owner: string | null;
  tag: string;
  deviceId: string | null;
  note: string | null;
  lastSeen: string | null;
  excludePing: string;
  PTRignore: string;
  editDate: string | null;
}

export interface Vlan {
  vlanId: string;
  domainId: string;
  name: string;
  number: string;
  description: string | null;
}

export interface Device {
  id: string;
  hostname: string;
  ip: string;
  description: string | null;
  sections: string | null;
  rack: string | null;
  rack_start: string | null;
  rack_size: string | null;
  location: string | null;
  type: string | null;
}

export interface Vrf {
  vrfId: string;
  name: string;
  rd: string | null;
  description: string | null;
}

export class PhpIPAMClient {
  private readonly http: AxiosInstance;
  private readonly appId: string;
  private readonly username: string | undefined;
  private readonly password: string | undefined;
  private readonly appToken: string | undefined;
  private token: string | null = null;

  constructor(config: PhpIPAMConfig) {
    this.appId = config.appId;
    this.username = config.username;
    this.password = config.password;
    this.appToken = config.appToken;

    if (this.appToken) {
      // App token mode: static token, no login needed.
      this.token = this.appToken;
    }

    this.http = axios.create({
      baseURL: config.baseUrl.replace(/\/$/, ""),
      timeout: 30_000,
      headers: { "Content-Type": "application/json" },
      httpsAgent: config.insecure
        ? new https.Agent({ rejectUnauthorized: false })
        : undefined,
    });
  }

  async authenticate(): Promise<void> {
    if (!this.username || !this.password) {
      throw new Error("phpIPAM user token mode requires username and password.");
    }
    const encoded = Buffer.from(`${this.username}:${this.password}`).toString("base64");
    const resp = await this.http.post<ApiResponse<{ token: string }>>(
      `/api/${this.appId}/user/`,
      {},
      { headers: { Authorization: `Basic ${encoded}` } }
    );
    const data = resp.data;
    if (!data.success || !data.data?.token) {
      throw new Error(`phpIPAM authentication failed: ${data.message ?? "no token returned"}`);
    }
    this.token = data.data.token;
  }

  private async request<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
    if (!this.token) {
      await this.authenticate();
    }

    // App token mode uses the `token` header; user token mode uses `phpipam-token`.
    const tokenHeader = this.appToken ? "token" : "phpipam-token";

    const doRequest = async (): Promise<T> => {
      const resp = await this.http.request<ApiResponse<T>>({
        method,
        url: path,
        data: body,
        headers: { [tokenHeader]: this.token! },
      });
      if (!resp.data.success) {
        throw new Error(resp.data.message ?? `API error ${resp.data.code}`);
      }
      return resp.data.data as T;
    };

    try {
      return await doRequest();
    } catch (err) {
      // App tokens are static — no re-auth on 401.
      if (!this.appToken && axios.isAxiosError(err) && err.response?.status === 401) {
        this.token = null;
        await this.authenticate();
        return doRequest();
      }
      throw err;
    }
  }

  private get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  // ── Sections ────────────────────────────────────────────────────────────────

  listSections(): Promise<Section[]> {
    return this.get(`/api/${this.appId}/sections/`);
  }

  getSection(id: number | string): Promise<Section> {
    return this.get(`/api/${this.appId}/sections/${id}/`);
  }

  // ── Subnets ─────────────────────────────────────────────────────────────────

  listSubnets(): Promise<Subnet[]> {
    return this.get(`/api/${this.appId}/subnets/`);
  }

  listSectionSubnets(sectionId: number | string): Promise<Subnet[]> {
    return this.get(`/api/${this.appId}/sections/${sectionId}/subnets/`);
  }

  getSubnet(id: number | string): Promise<Subnet> {
    return this.get(`/api/${this.appId}/subnets/${id}/`);
  }

  searchSubnets(term: string): Promise<Subnet[]> {
    return this.get(`/api/${this.appId}/subnets/search/${encodeURIComponent(term)}/`);
  }

  getSubnetUsage(id: number | string): Promise<SubnetUsage> {
    return this.get(`/api/${this.appId}/subnets/${id}/usage/`);
  }

  getFirstFreeAddress(subnetId: number | string): Promise<string> {
    return this.get(`/api/${this.appId}/subnets/${subnetId}/first_free/`);
  }

  listSubnetAddresses(subnetId: number | string): Promise<Address[]> {
    return this.get(`/api/${this.appId}/subnets/${subnetId}/addresses/`);
  }

  // ── Addresses ───────────────────────────────────────────────────────────────

  searchAddress(ip: string): Promise<Address[]> {
    return this.get(`/api/${this.appId}/addresses/search/${encodeURIComponent(ip)}/`);
  }

  getAddress(id: number | string): Promise<Address> {
    return this.get(`/api/${this.appId}/addresses/${id}/`);
  }

  // ── VLANs ───────────────────────────────────────────────────────────────────

  listVlans(): Promise<Vlan[]> {
    return this.get(`/api/${this.appId}/vlans/`);
  }

  searchVlans(term: string): Promise<Vlan[]> {
    return this.get(`/api/${this.appId}/vlans/search/${encodeURIComponent(term)}/`);
  }

  // ── Devices ─────────────────────────────────────────────────────────────────

  listDevices(): Promise<Device[]> {
    return this.get(`/api/${this.appId}/devices/`);
  }

  searchDevices(term: string): Promise<Device[]> {
    return this.get(`/api/${this.appId}/devices/search/${encodeURIComponent(term)}/`);
  }

  // ── VRFs ────────────────────────────────────────────────────────────────────

  listVrfs(): Promise<Vrf[]> {
    return this.get(`/api/${this.appId}/vrfs/`);
  }
}
