import {
  Route53Client,
  ListHostedZonesByNameCommand,
  GetHostedZoneCommand,
  ListResourceRecordSetsCommand,
  type HostedZone,
  type ResourceRecordSet,
} from "@aws-sdk/client-route-53";

export interface HostedZoneSummary {
  id: string;
  name: string;
  recordCount: number;
  comment?: string;
  privateZone: boolean;
}

export interface RecordSetSummary {
  name: string;
  type: string;
  ttl?: number;
  values: string[];
  aliasTarget?: string;
}

function stripZonePrefix(id: string): string {
  return id.replace(/^\/hostedzone\//, "");
}

export class Route53ClientWrapper {
  private client: Route53Client;

  constructor(region: string) {
    // Credentials resolve from the standard AWS SDK provider chain
    // (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars set by the
    // Start-Route53MCP.ps1 launcher) - never passed or stored here.
    this.client = new Route53Client({ region });
  }

  async listHostedZonesByName(dnsName?: string): Promise<HostedZoneSummary[]> {
    const zones: HostedZone[] = [];
    let nextDnsName = dnsName;
    let nextHostedZoneId: string | undefined;

    // Route53 paginates at 100 zones/page. Loop with a safety cap so a
    // large account can't spin forever, but still return everything for
    // realistic account sizes (this account has ~95 zones total).
    for (let page = 0; page < 20; page++) {
      const resp = await this.client.send(
        new ListHostedZonesByNameCommand({
          DNSName: nextDnsName,
          HostedZoneId: nextHostedZoneId,
        })
      );
      zones.push(...(resp.HostedZones ?? []));
      if (!resp.IsTruncated) break;
      nextDnsName = resp.NextDNSName;
      nextHostedZoneId = resp.NextHostedZoneId;
    }

    return zones.map((z) => ({
      id: stripZonePrefix(z.Id ?? ""),
      name: z.Name ?? "",
      recordCount: z.ResourceRecordSetCount ?? 0,
      comment: z.Config?.Comment,
      privateZone: z.Config?.PrivateZone ?? false,
    }));
  }

  async getHostedZone(hostedZoneId: string): Promise<{
    zone: HostedZoneSummary;
    nameServers: string[];
  }> {
    const resp = await this.client.send(
      new GetHostedZoneCommand({ Id: stripZonePrefix(hostedZoneId) })
    );
    if (!resp.HostedZone) {
      throw new Error(`Hosted zone ${hostedZoneId} not found`);
    }
    return {
      zone: {
        id: stripZonePrefix(resp.HostedZone.Id ?? ""),
        name: resp.HostedZone.Name ?? "",
        recordCount: resp.HostedZone.ResourceRecordSetCount ?? 0,
        comment: resp.HostedZone.Config?.Comment,
        privateZone: resp.HostedZone.Config?.PrivateZone ?? false,
      },
      nameServers: resp.DelegationSet?.NameServers ?? [],
    };
  }

  async listResourceRecordSets(
    hostedZoneId: string,
    startName?: string,
    startType?: string
  ): Promise<RecordSetSummary[]> {
    const records: ResourceRecordSet[] = [];
    let nextName = startName;
    let nextType = startType;
    let nextIdentifier: string | undefined;

    // Route53 paginates at 300 records/page. Safety cap of 10 pages
    // (3,000 records) - well beyond any zone in this account (largest
    // known is example.net at 113 records).
    for (let page = 0; page < 10; page++) {
      const resp = await this.client.send(
        new ListResourceRecordSetsCommand({
          HostedZoneId: stripZonePrefix(hostedZoneId),
          StartRecordName: nextName,
          StartRecordType: nextType as never,
          StartRecordIdentifier: nextIdentifier,
        })
      );
      records.push(...(resp.ResourceRecordSets ?? []));
      if (!resp.IsTruncated) break;
      nextName = resp.NextRecordName;
      nextType = resp.NextRecordType;
      nextIdentifier = resp.NextRecordIdentifier;
    }

    return records.map((r) => ({
      name: r.Name ?? "",
      type: r.Type ?? "",
      ttl: r.TTL,
      values: (r.ResourceRecords ?? []).map((v) => v.Value ?? ""),
      aliasTarget: r.AliasTarget?.DNSName,
    }));
  }
}
