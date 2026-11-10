import axios, { type AxiosInstance } from "axios";
import https from "node:https";

export interface PrtgConfig {
  baseUrl: string;
  apiToken: string;
  insecure?: boolean;
}

export interface PrtgAlarm {
  objid: number;
  name: string;
  status: string;
  message: string;
  device: string;
  group: string;
  priority: string;
  tags: string;
}

export interface PrtgSensor {
  objid: number;
  name: string;
  status: string;
  message: string;
  device: string;
  group: string;
  probe: string;
  lastvalue: string;
  priority: string;
  tags: string;
}

export interface PrtgSensorDetails {
  sensordata: {
    name: string;
    sensortype: string;
    intervaltext: string;
    statustext: string;
    lastcheck: string;
    lastup: string;
    lastdown: string;
    uptime: string;
    uptimetime: string;
    downtime: string;
    downtimetime: string;
    cumsince: string;
    message: string;
    tags: string;
    priority: string;
  };
}

// PRTG numeric status codes
export const PRTG_STATUS: Record<string, string> = {
  up: "3",
  warning: "4",
  down: "5",
  paused: "7",
  down_acknowledged: "13",
  down_partial: "14",
};

export class PrtgClient {
  private http: AxiosInstance;
  private token: string;

  constructor(config: PrtgConfig) {
    this.token = config.apiToken;
    const baseURL = config.baseUrl.endsWith("/") ? config.baseUrl : `${config.baseUrl}/`;

    this.http = axios.create({
      baseURL,
      timeout: 30_000,
      httpsAgent: new https.Agent({ rejectUnauthorized: !config.insecure }),
    });
  }

  private params(extra: Record<string, string | number | undefined> = {}): Record<string, string | number> {
    const p: Record<string, string | number> = { apitoken: this.token };
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined) p[k] = v;
    }
    return p;
  }

  async getActiveAlarms(options: {
    count?: number;
    statusFilter?: string;
  } = {}): Promise<{ alarms: PrtgAlarm[] }> {
    const ALARM_STATUSES = ["4", "5", "13", "14"]; // warning, down, down_acknowledged, down_partial
    const maxCount = options.count ?? 100;
    const columns = "objid,name,status,message,device,group,priority,tags";

    if (options.statusFilter) {
      const response = await this.http.get("api/table.json", {
        params: this.params({
          content: "sensors",
          count: maxCount,
          columns,
          filter_status: options.statusFilter,
        }),
      });
      return { alarms: (response.data.sensors ?? []) as PrtgAlarm[] };
    }

    const perStatus = Math.ceil(maxCount / ALARM_STATUSES.length);
    const responses = await Promise.all(
      ALARM_STATUSES.map((status) =>
        this.http.get("api/table.json", {
          params: this.params({
            content: "sensors",
            count: perStatus,
            columns,
            filter_status: status,
          }),
        })
      )
    );

    const alarms = responses.flatMap((r) => r.data.sensors ?? []) as PrtgAlarm[];
    return { alarms };
  }

  async getSensors(options: {
    count?: number;
    statusFilter?: string;
    nameFilter?: string;
    deviceFilter?: string;
    groupFilter?: string;
    probeFilter?: string;
    tagFilter?: string;
  } = {}): Promise<{ sensors: PrtgSensor[] }> {
    const response = await this.http.get("api/table.json", {
      params: this.params({
        content: "sensors",
        count: options.count ?? 200,
        columns: "objid,name,status,message,device,group,probe,lastvalue,priority,tags",
        ...(options.statusFilter ? { filter_status: options.statusFilter } : {}),
        ...(options.nameFilter ? { filter_name: `@sub(${options.nameFilter})` } : {}),
        ...(options.deviceFilter ? { filter_device: `@sub(${options.deviceFilter})` } : {}),
        ...(options.groupFilter ? { filter_group: `@sub(${options.groupFilter})` } : {}),
        ...(options.probeFilter ? { filter_probe: `@sub(${options.probeFilter})` } : {}),
        ...(options.tagFilter ? { filter_tags: `@sub(${options.tagFilter})` } : {}),
      }),
    });
    return response.data as { sensors: PrtgSensor[] };
  }

  async getSensorDetails(id: number): Promise<PrtgSensorDetails> {
    const response = await this.http.get("api/getsensordetails.json", {
      params: this.params({ id }),
    });
    return response.data as PrtgSensorDetails;
  }

  async pauseSensor(id: number, message: string, durationMinutes?: number): Promise<void> {
    await this.http.get("api/pause.htm", {
      params: this.params({
        id,
        action: 0,
        pausemsg: message,
        ...(durationMinutes ? { duration: durationMinutes } : {}),
      }),
    });
  }

  async resumeSensor(id: number): Promise<void> {
    await this.http.get("api/pause.htm", {
      params: this.params({ id, action: 1 }),
    });
  }
}
