#!/usr/bin/env python
#
# DNS management tool
#
# Copyright (C) Amitay Isaacs 2011
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os
import samba.getopt as options
import ldb
from struct import pack
from socket import inet_ntoa

from samba.netcmd import (
    Command,
    CommandError,
    Option,
    SuperCommand,
    )
from samba.dcerpc import dnsp, dnsserver
from samba.ndr import ndr_print


def dns_connect(server, lp, creds):
    binding_str = "ncacn_ip_tcp:%s[sign]" % server
    dns_conn = dnsserver.dnsserver(binding_str, lp, creds)
    return dns_conn

def bool_string(flag):
    if flag == 0:
        ret = 'FALSE'
    elif flag == 1:
        ret = 'TRUE'
    else:
        ret = 'UNKNOWN (0x%x)' % flag
    return ret

def enum_string(module, enum_defs, value):
    ret = None
    for e in enum_defs:
        if value == getattr(module, e):
            ret = e
            break
    if not ret:
        ret = 'UNKNOWN (0x%x)' % value
    return ret

def bitmap_string(module, bitmap_defs, value):
    ret = ''
    for b in bitmap_defs:
        if value & getattr(module, b):
            ret += '%s ' % b
    if not ret:
        ret = 'NONE'
    return ret

def boot_method_string(boot_method):
    enum_defs = [ 'DNS_BOOT_METHOD_UNINITIALIZED', 'DNS_BOOT_METHOD_FILE',
                    'DNS_BOOT_METHOD_REGISTRY', 'DNS_BOOT_METHOD_DIRECTORY' ]
    return enum_string(dnsserver, enum_defs, boot_method)

def name_check_flag_string(check_flag):
    enum_defs = [ 'DNS_ALLOW_RFC_NAMES_ONLY', 'DNS_ALLOW_NONRFC_NAMES',
                    'DNS_ALLOW_MULTIBYTE_NAMES', 'DNS_ALLOW_ALL_NAMES' ]
    return enum_string(dnsserver, enum_defs, check_flag)

def zone_type_string(zone_type):
    enum_defs = [ 'DNS_ZONE_TYPE_CACHE', 'DNS_ZONE_TYPE_PRIMARY',
                    'DNS_ZONE_TYPE_SECONDARY', 'DNS_ZONE_TYPE_STUB',
                    'DNS_ZONE_TYPE_FORWARDER', 'DNS_ZONE_TYPE_SECONDARY_CACHE' ]
    return enum_string(dnsp, enum_defs, zone_type)

def zone_update_string(zone_update):
    enum_defs = [ 'DNS_ZONE_UPDATE_OFF', 'DNS_ZONE_UPDATE_SECURE',
                    'DNS_ZONE_UPDATE_SECURE' ]
    return enum_string(dnsp, enum_defs, zone_update)

def zone_secondary_security_string(security):
    enum_defs = [ 'DNS_ZONE_SECSECURE_NO_SECURITY', 'DNS_ZONE_SECSECURE_NS_ONLY',
                    'DNS_ZONE_SECSECURE_LIST_ONLY', 'DNS_ZONE_SECSECURE_NO_XFER' ]
    return enum_string(dnsserver, enum_defs, security)

def zone_notify_level_string(notify_level):
    enum_defs = [ 'DNS_ZONE_NOTIFY_OFF', 'DNS_ZONE_NOTIFY_ALL_SECONDARIES',
                    'DNS_ZONE_NOTIFY_LIST_ONLY' ]
    return enum_string(dnsserver, enum_defs, notify_level)

def dp_flags_string(dp_flags):
    bitmap_defs = [ 'DNS_DP_AUTOCREATED', 'DNS_DP_LEGACY', 'DNS_DP_DOMAIN_DEFAULT',
                'DNS_DP_FOREST_DEFAULT', 'DNS_DP_ENLISTED', 'DNS_DP_DELETED' ]
    return bitmap_string(dnsserver, bitmap_defs, dp_flags)

def zone_flags_string(flags):
    bitmap_defs = [ 'DNS_RPC_ZONE_PAUSED', 'DNS_RPC_ZONE_SHUTDOWN',
                    'DNS_RPC_ZONE_REVERSE', 'DNS_RPC_ZONE_AUTOCREATED',
                    'DNS_RPC_ZONE_DSINTEGRATED', 'DNS_RPC_ZONE_AGING',
                    'DNS_RPC_ZONE_UPDATE_UNSECURE', 'DNS_RPC_ZONE_UPDATE_SECURE',
                    'DNS_RPC_ZONE_READONLY']
    return bitmap_string(dnsserver, bitmap_defs, flags)

def ip4_array_string(array):
    ret = []
    if not array:
        return ret
    for i in xrange(array.AddrCount):
        addr = '%s' % inet_ntoa(pack('i', array.AddrArray[i]))
        ret.append(addr)
    return ret

def dns_addr_array_string(array):
    ret = []
    if not array:
        return ret
    for i in xrange(array.AddrCount):
        if array.AddrArray[i].MaxSa[0] == 0x02:
            addr = '%d.%d.%d.%d (%d)' % \
                tuple(array.AddrArray[i].MaxSa[4:8] + [array.AddrArray[i].MaxSa[3]])
        elif array.AddrArray[i].MaxSa[0] == 0x17:
            addr = '%x%x:%x%x:%x%x:%x%x:%x%x:%x%x:%x%x:%x%x (%d)' % \
                tuple(array.AddrArray[i].MaxSa[4:20] + [array.AddrArray[i].MaxSa[3]])
        else:
            addr = 'UNKNOWN'
        ret.append(addr)
    return ret

def dns_type_flag(rec_type):
    rtype = rec_type.upper()
    if rtype == 'A':
        record_type = dnsp.DNS_TYPE_A
    elif rtype == 'NS':
        record_type = dnsp.DNS_TYPE_NS
    elif rtype == 'CNAME':
        record_type = dnsp.DNS_TYPE_CNAME
    elif rtype == 'SOA':
        record_type = dnsp.DNS_TYPE_SOA
    elif rtype == 'MX':
        record_type = dnsp.DNS_TYPE_MX
    elif rtype == 'SRV':
        record_type = dnsp.DNS_TYPE_SRV
    elif rtype == 'ALL':
        record_type = dnsp.DNS_TYPE_ALL
    else:
        raise CommandError('Unknown type of DNS record %s' % rec_type)
    return record_type

def dns_client_version(cli_version):
    version = cli_version.upper()
    if version == 'W2K':
        client_version = dnsserver.DNS_CLIENT_VERSION_W2K
    elif version == 'DOTNET':
        client_version = dnsserver.DNS_CLIENT_VERSION_DOTNET
    elif version == 'LONGHORN':
        client_version = dnsserver.DNS_CLIENT_VERSION_LONGHORN
    else:
        raise CommandError('Unknown client version %s' % cli_version)
    return client_version

def print_serverinfo(outf, typeid, serverinfo):
    outf.write('  dwVersion                   : 0x%x\n' % serverinfo.dwVersion)
    outf.write('  fBootMethod                 : %s\n' % boot_method_string(serverinfo.fBootMethod))
    outf.write('  fAdminConfigured            : %s\n' % bool_string(serverinfo.fAdminConfigured))
    outf.write('  fAllowUpdate                : %s\n' % bool_string(serverinfo.fAllowUpdate))
    outf.write('  fDsAvailable                : %s\n' % bool_string(serverinfo.fDsAvailable))
    outf.write('  pszServerName               : %s\n' % serverinfo.pszServerName)
    outf.write('  pszDsContainer              : %s\n' % serverinfo.pszDsContainer)

    if typeid != dnsserver.DNSSRV_TYPEID_SERVER_INFO:
        outf.write('  aipServerAddrs              : %s\n' %
                    ip4_array_string(serverinfo.aipServerAddrs))
        outf.write('  aipListenAddrs              : %s\n' %
                    ip4_array_string(serverinfo.aipListenAddrs))
        outf.write('  aipForwarders               : %s\n' %
                    ip4_array_string(serverinfo.aipForwarders))
    else:
        outf.write('  aipServerAddrs              : %s\n' %
                    dns_addr_array_string(serverinfo.aipServerAddrs))
        outf.write('  aipListenAddrs              : %s\n' %
                    dns_addr_array_string(serverinfo.aipListenAddrs))
        outf.write('  aipForwarders               : %s\n' %
                    dns_addr_array_string(serverinfo.aipForwarders))

    outf.write('  dwLogLevel                  : %d\n' % serverinfo.dwLogLevel)
    outf.write('  dwDebugLevel                : %d\n' % serverinfo.dwDebugLevel)
    outf.write('  dwForwardTimeout            : %d\n' % serverinfo.dwForwardTimeout)
    outf.write('  dwRpcPrototol               : 0x%x\n' % serverinfo.dwRpcProtocol)
    outf.write('  dwNameCheckFlag             : %s\n' % name_check_flag_string(serverinfo.dwNameCheckFlag))
    outf.write('  cAddressAnswerLimit         : %d\n' % serverinfo.cAddressAnswerLimit)
    outf.write('  dwRecursionRetry            : %d\n' % serverinfo.dwRecursionRetry)
    outf.write('  dwRecursionTimeout          : %d\n' % serverinfo.dwRecursionTimeout)
    outf.write('  dwMaxCacheTtl               : %d\n' % serverinfo.dwMaxCacheTtl)
    outf.write('  dwDsPollingInterval         : %d\n' % serverinfo.dwDsPollingInterval)
    outf.write('  dwScavengingInterval        : %d\n' % serverinfo.dwScavengingInterval)
    outf.write('  dwDefaultRefreshInterval    : %d\n' % serverinfo.dwDefaultRefreshInterval)
    outf.write('  dwDefaultNoRefreshInterval  : %d\n' % serverinfo.dwDefaultNoRefreshInterval)
    outf.write('  fAutoReverseZones           : %s\n' % bool_string(serverinfo.fAutoReverseZones))
    outf.write('  fAutoCacheUpdate            : %s\n' % bool_string(serverinfo.fAutoCacheUpdate))
    outf.write('  fRecurseAfterForwarding     : %s\n' % bool_string(serverinfo.fRecurseAfterForwarding))
    outf.write('  fForwardDelegations         : %s\n' % bool_string(serverinfo.fForwardDelegations))
    outf.write('  fNoRecursion                : %s\n' % bool_string(serverinfo.fNoRecursion))
    outf.write('  fSecureResponses            : %s\n' % bool_string(serverinfo.fSecureResponses))
    outf.write('  fRoundRobin                 : %s\n' % bool_string(serverinfo.fRoundRobin))
    outf.write('  fLocalNetPriority           : %s\n' % bool_string(serverinfo.fLocalNetPriority))
    outf.write('  fBindSecondaries            : %s\n' % bool_string(serverinfo.fBindSecondaries))
    outf.write('  fWriteAuthorityNs           : %s\n' % bool_string(serverinfo.fWriteAuthorityNs))
    outf.write('  fStrictFileParsing          : %s\n' % bool_string(serverinfo.fStrictFileParsing))
    outf.write('  fLooseWildcarding           : %s\n' % bool_string(serverinfo.fLooseWildcarding))
    outf.write('  fDefaultAgingState          : %s\n' % bool_string(serverinfo.fDefaultAgingState))

    if typeid != dnsserver.DNSSRV_TYPEID_SERVER_INFO_W2K:
        outf.write('  dwRpcStructureVersion       : 0x%x\n' % serverinfo.dwRpcStructureVersion)
        outf.write('  aipLogFilter                : %s\n' % dns_addr_array_string(serverinfo.aipLogFilter))
        outf.write('  pwszLogFilePath             : %s\n' % serverinfo.pwszLogFilePath)
        outf.write('  pszDomainName               : %s\n' % serverinfo.pszDomainName)
        outf.write('  pszForestName               : %s\n' % serverinfo.pszForestName)
        outf.write('  pszDomainDirectoryPartition : %s\n' % serverinfo.pszDomainDirectoryPartition)
        outf.write('  pszForestDirectoryPartition : %s\n' % serverinfo.pszForestDirectoryPartition)

        outf.write('  dwLocalNetPriorityNetMask   : 0x%x\n' % serverinfo.dwLocalNetPriorityNetMask)
        outf.write('  dwLastScavengeTime          : %d\n' % serverinfo.dwLastScavengeTime)
        outf.write('  dwEventLogLevel             : %d\n' % serverinfo.dwEventLogLevel)
        outf.write('  dwLogFileMaxSize            : %d\n' % serverinfo.dwLogFileMaxSize)
        outf.write('  dwDsForestVersion           : %d\n' % serverinfo.dwDsForestVersion)
        outf.write('  dwDsDomainVersion           : %d\n' % serverinfo.dwDsDomainVersion)
        outf.write('  dwDsDsaVersion              : %d\n' % serverinfo.dwDsDsaVersion)

    if typeid == dnsserver.DNSSRV_TYPEID_SERVER_INFO:
        outf.write('  fReadOnlyDC                 : %s\n' % bool_string(serverinfo.fReadOnlyDC))


def print_zoneinfo(outf, typeid, zoneinfo):
    outf.write('  pszZoneName                 : %s\n' % zoneinfo.pszZoneName)
    outf.write('  dwZoneType                  : %s\n' % zone_type_string(zoneinfo.dwZoneType))
    outf.write('  fReverse                    : %s\n' % bool_string(zoneinfo.fReverse))
    outf.write('  fAllowUpdate                : %s\n' % zone_update_string(zoneinfo.fAllowUpdate))
    outf.write('  fPaused                     : %s\n' % bool_string(zoneinfo.fPaused))
    outf.write('  fShutdown                   : %s\n' % bool_string(zoneinfo.fShutdown))
    outf.write('  fAutoCreated                : %s\n' % bool_string(zoneinfo.fAutoCreated))
    outf.write('  fUseDatabase                : %s\n' % bool_string(zoneinfo.fUseDatabase))
    outf.write('  pszDataFile                 : %s\n' % zoneinfo.pszDataFile)
    if typeid != dnsserver.DNSSRV_TYPEID_ZONE_INFO:
        outf.write('  aipMasters                  : %s\n' %
                    ip4_array_string(zoneinfo.aipMasters))
    else:
        outf.write('  aipMasters                  : %s\n' %
                    dns_addr_array_string(zoneinfo.aipMasters))
    outf.write('  fSecureSecondaries          : %s\n' % zone_secondary_security_string(zoneinfo.fSecureSecondaries))
    outf.write('  fNotifyLevel                : %s\n' % zone_notify_level_string(zoneinfo.fNotifyLevel))
    if typeid != dnsserver.DNSSRV_TYPEID_ZONE_INFO:
        outf.write('  aipSecondaries              : %s\n' %
                    ip4_array_string(zoneinfo.aipSecondaries))
        outf.write('  aipNotify                   : %s\n' %
                    ip4_array_string(zoneinfo.aipNotify))
    else:
        outf.write('  aipSecondaries              : %s\n' %
                    dns_addr_array_string(zoneinfo.aipSecondaries))
        outf.write('  aipNotify                   : %s\n' %
                    dns_addr_array_string(zoneinfo.aipNotify))
    outf.write('  fUseWins                    : %s\n' % bool_string(zoneinfo.fUseWins))
    outf.write('  fUseNbstat                  : %s\n' % bool_string(zoneinfo.fUseNbstat))
    outf.write('  fAging                      : %s\n' % bool_string(zoneinfo.fAging))
    outf.write('  dwNoRefreshInterval         : %d\n' % zoneinfo.dwNoRefreshInterval)
    outf.write('  dwRefreshInterval           : %d\n' % zoneinfo.dwRefreshInterval)
    outf.write('  dwAvailForScavengeTime      : %d\n' % zoneinfo.dwAvailForScavengeTime)
    if typeid != dnsserver.DNSSRV_TYPEID_ZONE_INFO:
        outf.write('  aipScavengeServers          : %s\n' %
                    ip4_array_string(zoneinfo.aipScavengeServers))
    else:
        outf.write('  aipScavengeServers          : %s\n' %
                    dns_addr_array_string(zoneinfo.aipScavengeServers))

    if typeid != dnsserver.DNSSRV_TYPEID_ZONE_INFO_W2K:
        outf.write('  dwRpcStructureVersion       : 0x%x\n' % zoneinfo.dwRpcStructureVersion)
        outf.write('  dwForwarderTimeout          : %d\n' % zoneinfo.dwForwarderTimeout)
        outf.write('  fForwarderSlave             : %d\n' % zoneinfo.fForwarderSlave)
        if typeid != dnsserver.DNSSRV_TYPEID_ZONE_INFO:
            outf.write('  aipLocalMasters             : %s\n' %
                        ip4_array_string(zoneinfo.aipLocalMasters))
        else:
            outf.write('  aipLocalMasters             : %s\n' %
                        dns_addr_array_string(zoneinfo.aipLocalMasters))
        outf.write('  dwDpFlags                   : %s\n' % dp_flags_string(zoneinfo.dwDpFlags))
        outf.write('  pszDpFqdn                   : %s\n' % zoneinfo.pszDpFqdn)
        outf.write('  pwszZoneDn                  : %s\n' % zoneinfo.pwszZoneDn)
        outf.write('  dwLastSuccessfulSoaCheck    : %d\n' % zoneinfo.dwLastSuccessfulSoaCheck)
        outf.write('  dwLastSuccessfulXfr         : %d\n' % zoneinfo.dwLastSuccessfulXfr)

    if typeid == dnsserver.DNSSRV_TYPEID_ZONE_INFO:
        outf.write('  fQueuedForBackgroundLoad    : %s\n' % bool_string(zoneinfo.fQueuedForBackgroundLoad))
        outf.write('  fBackgroundLoadInProgress   : %s\n' % bool_string(zoneinfo.fBackgroundLoadInProgress))
        outf.write('  fReadOnlyZone               : %s\n' % bool_string(zoneinfo.fReadOnlyZone))
        outf.write('  dwLastXfrAttempt            : %d\n' % zoneinfo.dwLastXfrAttempt)
        outf.write('  dwLastXfrResult             : %d\n' % zoneinfo.dwLastXfrResult)


def print_zone(outf, typeid, zone):
    outf.write('  pszZoneName                 : %s\n' % zone.pszZoneName)
    outf.write('  Flags                       : %s\n' % zone_flags_string(zone.Flags))
    outf.write('  ZoneType                    : %s\n' % zone_type_string(zone.ZoneType))
    outf.write('  Version                     : %s\n' % zone.Version)

    if typeid != dnsserver.DNSSRV_TYPEID_ZONE_W2K:
        outf.write('  dwDpFlags                   : %s\n' % dp_flags_string(zone.dwDpFlags))
        outf.write('  pszDpFqdn                   : %s\n' % zone.pszDpFqdn)


def print_enumzones(outf, typeid, zones):
    outf.write('  %d zone(s) found\n' % zones.dwZoneCount)
    for zone in zones.ZoneArray:
        outf.write('\n')
        print_zone(outf, typeid, zone)


def print_dns_record(outf, rec):
    mesg = 'Unknown: '
    if rec.wType == dnsp.DNS_TYPE_A:
        mesg = 'A: %s' % (rec.data)
    elif rec.wType == dnsp.DNS_TYPE_NS:
        mesg = 'NS: %s' % (rec.data.str)
    elif rec.wType == dnsp.DNS_TYPE_CNAME:
        mesg = 'CNAME: %s' % (rec.data.str)
    elif rec.wType == dnsp.DNS_TYPE_SOA:
        mesg = 'SOA: serial=%d, refresh=%d, retry=%d, expire=%d, ns=%s, email=%s' % (
                    rec.data.dwSerialNo,
                    rec.data.dwRefresh,
                    rec.data.dwRetry,
                    rec.data.dwExpire,
                    rec.data.NamePrimaryServer.str,
                    rec.data.ZoneAdministratorEmail.str)
    elif rec.wType == dnsp.DNS_TYPE_MX:
        mesg = 'MX: %s' % (rec.data.str)
    elif rec.wType == dnsp.DNS_TYPE_SRV:
        mesg = 'SRV: %s (%d)' % (rec.data.nameTarget.str, rec.data.wPort)
    outf.write('    %s (flags=%x, serial=%d, ttl=%d)\n' % (
                mesg, rec.dwFlags, rec.dwSerial, rec.dwTtlSeconds))


def print_dnsrecords(outf, records):
    for rec in records.rec:
        outf.write('  Name=%s, Records=%d, Children=%d\n' % (
                    rec.dnsNodeName.str,
                    rec.wRecordCount,
                    rec.dwChildCount))
        for dns_rec in rec.records:
                print_dns_record(outf, dns_rec)


class ARecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, ip_addr, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE,
                    node_flag=0):
        super(ARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_A
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = ip_addr

class AAAARecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, ip6_addr, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE,
                    node_flag=0):
        super(AAAARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_AAAA
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = ip6_addr

class CNameRecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, cname, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE,
                    node_flag=0):
        super(CNameRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_CNAME
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        cname_name = dnsserver.DNS_RPC_NAME()
        cname_name.str = cname
        cname_name.len = len(cname)
        self.data = cname_name

class NSRecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, dns_server, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE,
                    node_flag=0):
        super(NSRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_NS
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        ns = dnsserver.DNS_RPC_NAME()
        ns.str = dns_server
        ns.len = len(dns_server)
        self.data = ns

class SOARecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, mname, rname, serial=1, refresh=900, retry=600,
                 expire=86400, minimum=3600, ttl=3600, rank=dnsp.DNS_RANK_ZONE,
                 node_flag=dnsp.DNS_RPC_FLAG_AUTH_ZONE_ROOT):
        super(SOARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_SOA
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        soa = dnsserver.DNS_RPC_RECORD_SOA()
        soa.dwSerialNo = serial
        soa.dwRefresh = refresh
        soa.dwRetry = retry
        soa.dwExpire = expire
        soa.NamePrimaryServer.str = mname
        soa.NamePrimaryServer.len = len(mname)
        soa.ZoneAdministratorEmail.str = rname
        soa.ZoneAdministratorEmail.len = len(rname)
        self.data = soa

class SRVRecord(dnsserver.DNS_RPC_RECORD):
    def __init__(self, target, port, priority=0, weight=100, serial=1, ttl=900,
                rank=dnsp.DNS_RANK_ZONE, node_flag=0):
        super(SRVRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_SRV
        self.dwFlags = rank | node_flag
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        srv = dnsserver.DNS_RPC_RECORD_SRV()
        srv.wPriority = priority
        srv.wWeight = weight
        srv.wPort = port
        srv.nameTarget.str = target
        srv.nameTarget.len = len(target)
        self.data = srv

def dns_record_match(dns_conn, server, zone, name, record_type, data):
    select_flags = dnsserver.DNS_RPC_VIEW_AUTHORITY_DATA

    try:
        buflen, res = dns_conn.DnssrvEnumRecords2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                                    0,
                                                    server,
                                                    zone,
                                                    name,
                                                    None,
                                                    record_type,
                                                    select_flags,
                                                    None,
                                                    None)
    except RuntimeError, e:
        return None

    rec_match = None
    if res and res.count > 0:
        recs = res.rec[0]
        for rec in recs.records:
            if rec.wType == record_type:
                rec_match = rec
                break

    if rec_match:
        found = False
        if record_type == dnsp.DNS_TYPE_A:
            if rec_match.data == data:
                found = True
        elif record_type == dnsp.DNS_TYPE_AAAA:
            if rec_match.data == data:
                found = True
        elif record_type == dnsp.DNS_TYPE_CNAME:
            if rec_match.data == data:
                found = True
        elif record_type == dnsp.DNS_TYPE_NS:
            if rec_match.data == data:
                found = True

        if found:
            return rec_match

    return None


class cmd_serverinfo(Command):
    """Query for Server information"""

    synopsis = '%prog <server> [options]'

    takes_args = [ 'server' ]

    takes_options = [
        Option('--client-version', help='Client Version', default='longhorn',
                choices=['w2k','dotnet','longhorn'], dest='cli_ver'),
    ]

    def run(self, server, cli_ver, sambaopts=None, credopts=None, versionopts=None):
        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        client_version = dns_client_version(cli_ver)

        typeid, res = dns_conn.DnssrvQuery2(client_version,
                                            0,
                                            server,
                                            None,
                                            'ServerInfo')
        print_serverinfo(self.outf, typeid, res)


class cmd_zoneinfo(Command):
    """Query for zone information"""

    synopsis = '%prog <server> <zone> [options]'

    takes_args = [ 'server', 'zone' ]

    takes_options = [
        Option('--client-version', help='Client Version', default='longhorn',
                choices=['w2k','dotnet','longhorn'], dest='cli_ver'),
    ]

    def run(self, server, zone, cli_ver, sambaopts=None, credopts=None, versionopts=None):
        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        client_version = dns_client_version(cli_ver)

        typeid, res = dns_conn.DnssrvQuery2(client_version,
                                            0,
                                            server,
                                            zone,
                                            'ZoneInfo')
        print_zoneinfo(self.outf, typeid, res)


class cmd_zonelist(Command):
    """Query for zones"""

    synopsis = '%prog <server> [options]'

    takes_args = [ 'server' ]

    takes_options = [
        Option('--client-version', help='Client Version', default='longhorn',
                choices=['w2k','dotnet','longhorn'], dest='cli_ver'),
        Option('--primary', help='List primary zones (default)',
                action='store_true', dest='primary'),
        Option('--secondary', help='List secondary zones',
                action='store_true', dest='secondary'),
        Option('--cache', help='List cached zones',
                action='store_true', dest='cache'),
        Option('--auto', help='List automatically created zones',
                action='store_true', dest='auto'),
        Option('--forward', help='List forward zones',
                action='store_true', dest='forward'),
        Option('--reverse', help='List reverse zones',
                action='store_true', dest='reverse'),
        Option('--ds', help='List directory integrated zones',
                action='store_true', dest='ds'),
        Option('--non-ds', help='List non-directory zones',
                action='store_true', dest='nonds')
    ]

    def run(self, server, cli_ver, primary=False, secondary=False, cache=False,
                auto=False, forward=False, reverse=False, ds=False, nonds=False,
                sambaopts=None, credopts=None, versionopts=None):
        request_filter = 0

        if primary:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_PRIMARY
        if secondary:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_SECONDARY
        if cache:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_CACHE
        if auto:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_AUTO
        if forward:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_FORWARD
        if reverse:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_REVERSE
        if ds:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_DS
        if nonds:
            request_filter |= dnsserver.DNS_ZONE_REQUEST_NON_DS

        if request_filter == 0:
            request_filter = dnsserver.DNS_ZONE_REQUEST_PRIMARY

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        client_version = dns_client_version(cli_ver)

        typeid, res = dns_conn.DnssrvComplexOperation2(client_version,
                                                        0,
                                                        server,
                                                        None,
                                                        'EnumZones',
                                                        dnsserver.DNSSRV_TYPEID_DWORD,
                                                        request_filter)

        if client_version == dnsserver.DNS_CLIENT_VERSION_W2K:
            typeid = dnsserver.DNSSRV_TYPEID_ZONE_W2K
        else:
            typeid = dnsserver.DNSSRV_TYPEID_ZONE
        print_enumzones(self.outf, typeid, res)


class cmd_query(Command):
    """Query a name"""

    synopsis = '%prog <server> <zone> <name> <type> [options]'

    takes_args = [ 'server', 'zone', 'name', 'rtype' ]

    takes_options = [
        Option('--authority', help='Search authoritative records (default)',
                action='store_true', dest='authority'),
        Option('--cache', help='Search cached records',
                action='store_true', dest='cache'),
        Option('--glue', help='Search glue records',
                action='store_true', dest='glue'),
        Option('--root', help='Search root hints',
                action='store_true', dest='root'),
        Option('--additional', help='List additional records',
                action='store_true', dest='additional'),
        Option('--no-children', help='Do not list children',
                action='store_true', dest='no_children'),
        Option('--only-children', help='List only children',
                action='store_true', dest='only_children')
    ]

    def run(self, server, zone, name, rtype, authority=False, cache=False, glue=False,
                root=False, additional=False, no_children=False, only_children=False,
                sambaopts=None, credopts=None, versionopts=None):
        record_type = dns_type_flag(rtype)

        select_flags = 0
        if authority:
            select_flags |= dnsserver.DNS_RPC_VIEW_AUTHORITY_DATA
        if cache:
            select_flags |= dnsserver.DNS_RPC_VIEW_CACHE_DATA
        if glue:
            select_flags |= dnsserver.DNS_RPC_VIEW_GLUE_DATA
        if root:
            select_flags |= dnsserver.DNS_RPC_VIEW_ROOT_HINT_DATA
        if additional:
            select_flags |= dnsserver.DNS_RPC_VIEW_ADDITIONAL_DATA
        if no_children:
            select_flags |= dnsserver.DNS_RPC_VIEW_NO_CHILDREN
        if only_children:
            select_flags |= dnsserver.DNS_RPC_VIEW_ONLY_CHILDREN

        if select_flags == 0:
            select_flags = dnsserver.DNS_RPC_VIEW_AUTHORITY_DATA

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        buflen, res = dns_conn.DnssrvEnumRecords2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                                    0,
                                                    server,
                                                    zone,
                                                    name,
                                                    None,
                                                    record_type,
                                                    select_flags,
                                                    None,
                                                    None)
        print_dnsrecords(self.outf, res)


class cmd_roothints(Command):
    """Query root hints"""

    synopsis = '%prog <server> [<name>] [options]'

    takes_args = [ 'server', 'name?' ]

    def run(self, server, name='.', sambaopts=None, credopts=None, versionopts=None):
        record_type = dnsp.DNS_TYPE_NS
        select_flags = (dnsserver.DNS_RPC_VIEW_ROOT_HINT_DATA |
                        dnsserver.DNS_RPC_VIEW_ADDITIONAL_DATA)

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        buflen, res = dns_conn.DnssrvEnumRecords2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                                    0,
                                                    server,
                                                    '..RootHints',
                                                    name,
                                                    None,
                                                    record_type,
                                                    select_flags,
                                                    None,
                                                    None)
        print_dnsrecords(self.outf, res)


class cmd_add_record(Command):
    """Add a DNS record"""

    synopsis = '%prog <server> <zone> <name> <A|AAAA|CNAME|NS> <data>'

    takes_args = [ 'server', 'zone', 'name', 'rtype', 'data' ]

    def run(self, server, zone, name, rtype, data, sambaopts=None, credopts=None, versionopts=None):

        record_type = dns_type_flag(rtype)

        if record_type == dnsp.DNS_TYPE_A:
            rec = ARecord(data)
        elif record_type == dnsp.DNS_TYPE_AAAA:
            rec = AAAARecord(data)
        elif record_type == dnsp.DNS_TYPE_CNAME:
            rec = CNameRecord(data)
        elif record_type == dnsp.DNS_TYPE_NS:
            rec = NSRecord(data)
        else:
            raise CommandError('Adding record of type %s is not supported' % rtype)

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        rec_match = dns_record_match(dns_conn, server, zone, name, record_type, data)
        if rec_match is not None:
            raise CommandError('Record already exists')

        add_rec_buf = dnsserver.DNS_RPC_RECORD_BUF()
        add_rec_buf.rec = rec

        dns_conn.DnssrvUpdateRecord2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                        0,
                                        server,
                                        zone,
                                        name,
                                        add_rec_buf,
                                        None)
        self.outf.write('Record added succefully\n')


class cmd_update_record(Command):
    """Update a DNS record"""

    synopsis = '%prog <server> <zone> <name> <A|AAAA|CNAME|NS> <olddata> <newdata>'

    takes_args = [ 'server', 'zone', 'name', 'rtype', 'olddata', 'newdata' ]

    def run(self, server, zone, name, rtype, olddata, newdata,
                sambaopts=None, credopts=None, versionopts=None):

        record_type = dns_type_flag(rtype)
        if record_type == dnsp.DNS_TYPE_A:
            rec = ARecord(newdata)
        elif record_type == dnsp.DNS_TYPE_AAAA:
            rec = AAAARecord(newdata)
        elif record_type == dnsp.DNS_TYPE_CNAME:
            rec = CNameRecord(newdata)
        elif record_type == dnsp.DNS_TYPE_NS:
            rec = NSRecord(newdata)
        else:
            raise CommandError('Updating record of type %s is not supported' % rtype)

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        rec_match = dns_record_match(dns_conn, server, zone, name, record_type, olddata)
        if not rec_match:
            raise CommandError('Record does not exist')

        # Copy properties from existing record to new record
        rec.dwFlags = rec_match.dwFlags
        rec.dwSerial = rec_match.dwSerial
        rec.dwTtlSeconds = rec_match.dwTtlSeconds
        rec.dwTimeStamp = rec_match.dwTimeStamp

        add_rec_buf = dnsserver.DNS_RPC_RECORD_BUF()
        add_rec_buf.rec = rec

        del_rec_buf = dnsserver.DNS_RPC_RECORD_BUF()
        del_rec_buf.rec = rec_match

        dns_conn.DnssrvUpdateRecord2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                        0,
                                        server,
                                        zone,
                                        name,
                                        add_rec_buf,
                                        del_rec_buf)
        self.outf.write('Record updated succefully\n')


class cmd_delete_record(Command):
    """Delete a DNS record"""

    synopsis = '%prog <server> <zone> <name> <A|AAAA|CNAME|NS> <data>'

    takes_args = [ 'server', 'zone', 'name', 'rtype', 'data' ]

    def run(self, server, zone, name, rtype, data, sambaopts=None, credopts=None, versionopts=None):

        record_type = dns_type_flag(rtype)

        if record_type == dnsp.DNS_TYPE_A:
            rec = ARecord(data)
        elif record_type == dnsp.DNS_TYPE_AAAA:
            rec = AAAARecord(data)
        elif record_type == dnsp.DNS_TYPE_CNAME:
            rec = CNameRecord(data)
        elif record_type == dnsp.DNS_TYPE_NS:
            rec = NSRecord(data)
        else:
            raise CommandError('Deleting record of type %s is not supported' % rtype)

        self.lp = sambaopts.get_loadparm()
        self.creds = credopts.get_credentials(self.lp)
        dns_conn = dns_connect(server, self.lp, self.creds)

        rec_match = dns_record_match(dns_conn, server, zone, name, record_type, data)
        if not rec_match:
            raise CommandError('Record does not exist')

        del_rec_buf = dnsserver.DNS_RPC_RECORD_BUF()
        del_rec_buf.rec = rec_match

        dns_conn.DnssrvUpdateRecord2(dnsserver.DNS_CLIENT_VERSION_LONGHORN,
                                        0,
                                        server,
                                        zone,
                                        name,
                                        None,
                                        del_rec_buf)
        self.outf.write('Record deleted succefully\n')


class cmd_dns(SuperCommand):
    """Domain Name Service (DNS) management"""

    subcommands = {}
    subcommands['serverinfo'] = cmd_serverinfo()
    subcommands['zoneinfo'] = cmd_zoneinfo()
    subcommands['zonelist'] = cmd_zonelist()
    subcommands['query'] = cmd_query()
    subcommands['roothints'] = cmd_roothints()
    subcommands['add'] = cmd_add_record()
    subcommands['update'] = cmd_update_record()
    subcommands['delete'] = cmd_delete_record()