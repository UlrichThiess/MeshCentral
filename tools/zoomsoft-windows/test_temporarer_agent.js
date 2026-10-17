// Run the real MeshCentral disconnect handler; no network or installed agent.
'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { EventEmitter } = require('node:events');
const { CreateMeshAgent } = require('../../meshagent');

for (const temporary of [true, false]) {
    test(temporary ? 'temporary device disappears on websocket close' : 'persistent device is retained on websocket close', () => {
        const removed = [], events = [], offline = [];
        const db = {
            Remove: id => removed.push(id),
            RemoveSMBIOS: id => removed.push('smbios:' + id),
            RemoveAllNodeEvents: (domain, id) => removed.push('events:' + id),
            removeAllPowerEventsForNode: id => removed.push('power:' + id)
        };
        const parent = {
            agentStats: { createMeshAgentCount: 0, agentClose: 0 },
            trafficStats: { AgentCtrlIn: 0, AgentCtrlOut: 0 },
            crypto: require('node:crypto'),
            meshes: { 'mesh//test': { flags: 0 } },
            wsagents: {}, wsagentsDisconnections: {},
            CreateMeshDispatchTargets: () => [],
            parent: {
                certificateOperations: { forge: {} }, common: {}, debug: () => {},
                ClearConnectivityState: (...args) => offline.push(args),
                GetConnectivityState: () => null,
                DispatchEvent: (targets, source, event) => events.push(event)
            }
        };
        const ws = new EventEmitter();
        ws._socket = { remotePort: 1234, bytesRead: 0, bytesWritten: 0 };
        const agent = CreateMeshAgent(parent, db, ws, { clientIp: '127.0.0.1' }, { agentidletimeout: 0 }, { id: '' });
        agent.dbNodeKey = 'node//test';
        agent.dbMeshKey = 'mesh//test';
        agent.nodeid = 'test';
        agent.agentInfo = { agentId: 4, capabilities: temporary ? 0x20 : 0x01 };
        parent.wsagents[agent.dbNodeKey] = agent;
        ws.emit('close');
        assert.equal(parent.wsagents['node//test'], undefined);
        assert.equal(offline.length, 1);
        assert.equal(removed.includes('node//test'), temporary);
        assert.equal(removed.includes('ifnode//test'), temporary);
        assert.equal(removed.includes('events:node//test'), temporary);
        assert.equal(events.some(event => event.action === 'removenode' && event.nodeid === 'node//test'), temporary);
    });
}
