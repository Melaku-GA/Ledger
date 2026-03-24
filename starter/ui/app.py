"""
UI Interface for The Ledger Demonstration (Standalone)
=======================================================
A simple HTTP server to demonstrate The Ledger functionality.

Run: python ui/app.py
Then open http://localhost:5000 in your browser
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncio
import json
from aiohttp import web
from src.mcp.server import MCPLedgerServer, handle_tool_call, handle_resource_call

server = MCPLedgerServer()

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Ledger - Apex Financial Services</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(90deg, #0f3460, #16213e);
            padding: 20px;
            text-align: center;
            border-bottom: 2px solid #e94560;
        }
        .header h1 { color: #e94560; font-size: 2.5em; }
        .header p { color: #888; margin-top: 5px; }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .panel {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #333;
        }
        
        .panel h2 {
            color: #e94560;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
            margin-bottom: 15px;
            font-size: 1.2em;
        }
        
        .panel h3 {
            color: #aaa;
            margin: 15px 0 10px 0;
            font-size: 0.9em;
            text-transform: uppercase;
        }
        
        .btn {
            background: #e94560;
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 12px;
            margin: 3px;
            transition: all 0.3s;
        }
        .btn:hover { background: #ff6b6b; transform: translateY(-2px); }
        .btn:disabled { background: #555; cursor: not-allowed; }
        
        .btn-group { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 15px; }
        
        .log {
            background: #0d0d0d;
            border-radius: 5px;
            padding: 15px;
            height: 350px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 11px;
        }
        .log-entry { margin-bottom: 6px; padding: 5px; border-left: 3px solid #333; }
        .log-entry.success { border-left-color: #4caf50; }
        .log-entry.error { border-left-color: #f44336; }
        .log-entry.info { border-left-color: #2196f3; }
        .log-timestamp { color: #666; }
        
        .event-list {
            background: #0d0d0d;
            border-radius: 5px;
            padding: 15px;
            height: 350px;
            overflow-y: auto;
        }
        .event-item {
            padding: 8px;
            margin-bottom: 6px;
            background: #1a1a2e;
            border-radius: 5px;
            border-left: 3px solid #e94560;
            font-size: 11px;
        }
        .event-type { color: #e94560; font-weight: bold; }
        .event-position { color: #666; font-size: 10px; }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-bottom: 15px;
        }
        .stat-card {
            background: #16213e;
            padding: 12px;
            border-radius: 5px;
            text-align: center;
        }
        .stat-value { font-size: 20px; color: #e94560; font-weight: bold; }
        .stat-label { color: #888; font-size: 10px; }
        
        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 11px;
            background: #333;
        }
        .status-submitted { background: #2196f3; }
        .status-approved { background: #4caf50; }
        
        @media (max-width: 768px) {
            .container { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>The Ledger</h1>
        <p>Apex Financial Services - Enterprise Audit Infrastructure</p>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Control Panel</h2>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value" id="eventCount">0</div>
                    <div class="stat-label">Events</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="agentCount">0</div>
                    <div class="stat-label">Agents</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="complianceCount">0</div>
                    <div class="stat-label">Compliance</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="status">-</div>
                    <div class="stat-label">Status</div>
                </div>
            </div>
            
            <h3>1. Agent Sessions (Gas Town)</h3>
            <div class="btn-group">
                <button class="btn" onclick="startAgent('credit')">Credit Agent</button>
                <button class="btn" onclick="startAgent('fraud')">Fraud Agent</button>
            </div>
            
            <h3>2. Application Flow</h3>
            <div class="btn-group">
                <button class="btn" onclick="submitApp()">Submit</button>
                <button class="btn" onclick="creditAnalysis()">Credit Analysis</button>
                <button class="btn" onclick="fraudScreening()">Fraud Screening</button>
                <button class="btn" onclick="complianceCheck()">Compliance</button>
            </div>
            
            <h3>3. Decision</h3>
            <div class="btn-group">
                <button class="btn" onclick="generateDecision()">Generate Decision</button>
                <button class="btn" onclick="humanReview()">Human Review</button>
            </div>
            
            <h3>4. Query</h3>
            <div class="btn-group">
                <button class="btn" onclick="queryAudit()">Audit Trail</button>
                <button class="btn" onclick="queryCompliance()">Compliance</button>
                <button class="btn" onclick="integrityCheck()">Integrity</button>
            </div>
            
            <h3>Reset</h3>
            <div class="btn-group">
                <button class="btn" onclick="reset()">Reset Demo</button>
            </div>
        </div>
        
        <div class="panel">
            <h2>Event Log</h2>
            <div class="log" id="log"></div>
        </div>
        
        <div class="panel" style="grid-column: span 2;">
            <h2>Event Stream</h2>
            <div class="event-list" id="events">
                <div style="color: #666; text-align: center; padding: 40px;">
                    Click buttons to run the demo
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let events = [];
        let agents = new Set();
        let appId = 'APP-' + Math.floor(Math.random() * 10000);
        let complianceCount = 0;
        let creditSessionId = null;
        let fraudSessionId = null;
        
        function log(msg, type='info') {
            const div = document.getElementById('log');
            const e = document.createElement('div');
            e.className = 'log-entry ' + type;
            e.innerHTML = '<span class="log-timestamp">' + new Date().toLocaleTimeString() + '</span> ' + msg;
            div.insertBefore(e, div.firstChild);
        }
        
        function updateStats() {
            document.getElementById('eventCount').textContent = events.length;
            document.getElementById('agentCount').textContent = agents.size;
            document.getElementById('complianceCount').textContent = complianceCount;
        }
        
        async function api(tool, args) {
            const r = await fetch('/api/tool', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tool, args})
            });
            return await r.json();
        }
        
        async function get(uri) {
            const r = await fetch('/api/resource', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({uri})
            });
            return await r.json();
        }
        
        async function startAgent(type) {
            const cfg = {
                credit: {id: 'credit-agent', sess: 'sess-cred-' + Date.now(), type: 'CreditAnalysis', ver: 'v2.3'},
                fraud: {id: 'fraud-agent', sess: 'sess-fraud-' + Date.now(), type: 'FraudDetection', ver: 'v1.5'}
            }[type];
            
            // Store session IDs for this application
            if (type === 'credit') creditSessionId = cfg.sess;
            if (type === 'fraud') fraudSessionId = cfg.sess;
            
            const result = await api('start_agent_session', {
                agent_id: cfg.id, session_id: cfg.sess, agent_type: cfg.type,
                model_version: cfg.ver, context_source: 'loan_app', context_token_count: 5000
            });
            
            if (result.success) {
                agents.add(cfg.id);
                log('Started ' + cfg.type + ' (' + cfg.ver + ')', 'success');
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
        }
        
        async function submitApp() {
            const result = await api('submit_application', {
                application_id: appId, applicant_id: 'Acme Corp',
                requested_amount_usd: 500000, loan_purpose: 'Working Capital'
            });
            
            if (result.success) {
                log('Submitted ' + appId, 'success');
                document.getElementById('status').textContent = 'SUBMITTED';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function creditAnalysis() {
            const result = await api('record_credit_analysis', {
                application_id: appId, agent_id: 'credit-agent', session_id: creditSessionId || 'sess-cred-1',
                model_version: 'v2.3', confidence_score: 0.85, risk_tier: 'LOW',
                recommended_limit_usd: 500000, input_data: {score: 750}
            });
            
            if (result.success) {
                log('Credit analysis: risk=LOW, confidence=0.85', 'success');
                document.getElementById('status').textContent = 'CREDIT_OK';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function fraudScreening() {
            const result = await api('record_fraud_screening', {
                application_id: appId, agent_id: 'fraud-agent', session_id: fraudSessionId || 'sess-fraud-1',
                fraud_score: 0.1, anomaly_flags: [], screening_model_version: 'v1.5', input_data: {}
            });
            
            if (result.success) {
                log('Fraud screening: score=0.1 (low)', 'success');
                document.getElementById('status').textContent = 'FRAUD_OK';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function complianceCheck() {
            const result = await api('record_compliance_check', {
                application_id: appId, rule_id: 'KYB', rule_version: '2026-Q1',
                passed: true, evidence_hash: 'abc123'
            });
            
            if (result.success) {
                complianceCount++;
                log('Compliance: KYB passed', 'success');
                document.getElementById('status').textContent = 'COMPLIANT';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function generateDecision() {
            const result = await api('generate_decision', {
                application_id: appId, orchestrator_agent_id: 'orchestrator',
                confidence_score: 0.85, recommendation: 'APPROVE',
                contributing_sessions: [creditSessionId || 'sess-cred-1', fraudSessionId || 'sess-fraud-1']
            });
            
            if (result.success) {
                log('Decision: ' + result.data.recommendation, 'success');
                document.getElementById('status').textContent = 'DECISION';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function humanReview() {
            const result = await api('record_human_review', {
                application_id: appId, reviewer_id: 'john-smith',
                override: false, final_decision: 'APPROVE'
            });
            
            if (result.success) {
                log('Human review: APPROVED', 'success');
                document.getElementById('status').textContent = 'APPROVED';
            } else {
                log('Error: ' + result.error.message, 'error');
            }
            updateStats();
            queryAudit();
        }
        
        async function queryAudit() {
            const result = await get('ledger://applications/' + appId + '/audit-trail');
            
            if (result.success) {
                events = result.data.events || [];
                const div = document.getElementById('events');
                div.innerHTML = events.map(e => 
                    '<div class="event-item"><span class="event-type">' + e.event_type + 
                    '</span> <span class="event-position">@' + e.stream_position + '</span></div>'
                ).join('');
                log(events.length + ' events loaded', 'info');
            }
        }
        
        async function queryCompliance() {
            const result = await get('ledger://applications/' + appId + '/compliance');
            if (result.success) {
                log('Compliance: ' + result.data.checks_passed + ' passed', 'info');
            }
        }
        
        async function integrityCheck() {
            const result = await api('run_integrity_check', {entity_type: 'loan', entity_id: appId});
            if (result.success) {
                log('Integrity: ' + (result.data.chain_valid ? 'VALID' : 'INVALID'), 
                    result.data.chain_valid ? 'success' : 'error');
            }
        }
        
        async function reset() {
            events = [];
            agents = new Set();
            appId = 'APP-' + Math.floor(Math.random() * 10000);
            complianceCount = 0;
            creditSessionId = null;
            fraudSessionId = null;
            document.getElementById('log').innerHTML = '';
            document.getElementById('events').innerHTML = '<div style="color:#666;text-align:center;padding:40px;">Click buttons to run</div>';
            document.getElementById('status').textContent = '-';
            updateStats();
            log('Reset complete', 'info');
        }
    </script>
</body>
</html>
'''

async def handle_tool(request):
    data = await request.json()
    result = await handle_tool_call(data['tool'], data.get('args', {}), server)
    # Convert dataclass to dict if needed
    if hasattr(result, '__dict__'):
        result = result.__dict__
    return web.json_response(result)

async def handle_resource(request):
    data = await request.json()
    result = await handle_resource_call(data['uri'], server)
    # Convert dataclass to dict if needed
    if hasattr(result, '__dict__'):
        result = result.__dict__
    return web.json_response(result)

async def index(request):
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')

app = web.Application()
app.router.add_get('/', index)
app.router.add_post('/api/tool', handle_tool)
app.router.add_post('/api/resource', handle_resource)

if __name__ == '__main__':
    print("="*60)
    print("THE LEDGER - UI Demonstration")
    print("="*60)
    print("Open http://localhost:5000 in your browser")
    print("="*60)
    web.run_app(app, port=5000)
