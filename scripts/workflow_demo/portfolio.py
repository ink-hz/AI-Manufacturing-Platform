"""Six small, linked Chinese fictional manufacturing projects at useful stages."""
from datetime import datetime, timedelta

PORTFOLIO = [
    ('shortage', '自研相机', '星澜工业相机 SC-240', '澄禾视觉实验室', 12, '镜头组件缺料待补齐'),
    ('quality', '数采相机', '云岑数采相机 DC-810', '禾川自动化研究社', 8, '试产测试异常待返工'),
    ('printer', '3D 打印机', '栖木桌面打印机 P-220', '青屿创客工坊', 5, '首件测试完成待检验'),
    ('oem', 'OEM 代工代料', '凌舟协作机器人 OEM-R6', '北岚装备设计室', 10, '客供料与客户图纸协同'),
    ('partial', '自研相机', '星澜工业相机 SC-120', '舟浦光学工作室', 6, '首批已交付余量待出货'),
    ('aftercare', '数采相机', '云岑数采相机 DC-420', '远汀测控实验室', 4, '全部验收售后改进中'),
]


class Scenario:
    def __init__(self, seed, entry):
        self.seed = seed
        self.key, self.line, self.product, customer, self.quantity, self.stage = entry
        self.customer = '【模拟】' + customer
        self.at = datetime.fromisoformat(seed.manifest['started_at'])
        self.printer = self.key == 'printer'
        self.oem = self.key == 'oem'
        self.materials = [('客供主控板' if self.oem else '高温喷头总成' if self.printer else '低噪声图像采集板', self.customer if self.oem else '【模拟】制造方自有')]
        if self.oem:
            self.materials.append(('机器人关节结构总成', '【模拟】制造方自有'))
        elif self.key == 'shortage':
            self.materials.append(('定焦工业镜头 12mm', '【模拟】制造方自有'))
        spec = dict(operation_id=seed.ident('operation/' + self.key + '/project'),
            name='【模拟】' + self.product + '小批交付项目', line_id=self.line, product=self.product,
            customer_id=self.customer, mode='oem' if self.oem else 'internal', unit=dict(code='台', scale=0), quantity=str(self.quantity),
            contract=dict(customer_approval_required=self.oem, customer_release_required=self.oem, acceptance_required=True,
                customer_revision='C-A.1', internal_revision='M-A.1', material_ownership_rules='【模拟】客供主控板归客户；自采结构件与电子部件归制造方；按批次追溯领用与余料'))
        self.pid = seed.step(self.key + '/project', 'project', spec)['id']
        for role in ['engineering', 'planner', 'supply', 'production', 'quality', 'warehouse']:
            from seed_workflow_demo import QUALIFICATIONS
            seed.grant(self.key + '/grant/' + role, self.pid, str(seed.actors[role].user_id), [role], QUALIFICATIONS.get(role, []))
        from seed_workflow_demo import ROLES
        for owner in seed.config['owner_ids']:
            seed.grant(self.key + '/owner/' + owner, self.pid, owner, ROLES)

    def source(self, label, kind):
        return self.seed.source(self.key + '/' + label, kind)

    def c(self, label, action, actor='maintenance', **fields):
        return self.seed.command(self.key + '/' + label, self.pid, action, actor, **fields)

    def value(self, kind, oid):
        return self.seed.obj(self.pid, kind, oid)

    def foundation(self):
        due = (self.at + timedelta(days=14)).date().isoformat()
        demand = self.c('demand', 'demand.record', kind='firm', product=self.product, quantity=str(self.quantity), unit='台', due_date=due, source=self.source('demand', 'demand'))['object_id']
        for dimension, text in [('technical', '产品接口与图纸范围'), ('material', '物料交期与供货风险'), ('capacity', '小批装配工位排程'), ('commercial', '分批交付与验收条款'), ('quality', '测试规格与独立放行要求')]:
            self.c('review/' + dimension, 'demand.review', demand_id=demand, dimension=dimension, decision='approved', evidence='【模拟】评审通过：' + text + '；缺料与客户批准仍由执行门禁控制')
        self.order = self.c('order', 'order.register', demand_id=demand, quantity=str(self.quantity), unit='台', due_date=due, source=self.source('sales-order', 'order_line'))['object_id']
        self.limit = dict(name='喷头稳定温度' if self.printer else '主电源输出电压', unit='℃' if self.printer else 'V', lower='195' if self.printer else '4.85', upper='205' if self.printer else '5.15')
        self.route = '喷头装配校准' if self.printer else '整机装配与接口校准'
        self.revision = self.c('revision', 'engineering.revision', 'engineering', package_id='DEMO-' + self.product, revision='M-A.1', internal_revision='M-A.1', customer_revision='C-A.1',
            items=[dict(id='DEMO-MBOM', kind='mbom', title='【模拟】' + self.product + '制造BOM：每台各1件（客供/自采分列）', revision='M-A.1', status='verified', evidence='【模拟】' + ('客户设计包C-A.1转制造BOM；客供主控板、自采机器人关节结构总成，客户正式批准待办' if self.oem else '工程维护身份核对小批物料表与装配用量')), dict(id='DEMO-DRAWING', kind='drawing', title='【模拟】' + self.product + '总装图与接口表', revision='M-A.1', status='verified', evidence='【模拟】工程维护身份核对图纸；不代表实际客户批准')],
            route_steps=[dict(station=self.route, instruction_version='DEMO-SOP-A.1')],
            test_spec=dict(version='DEMO-LIMIT-A.1', program_version='DEMO-TEST-A.1', measurements=[self.limit]), firmware_version='DEMO-FW-1.4')['object_id']
        self.c('handoff', 'engineering.handoff', 'engineering', revision_id=self.revision, to_system='MES', received_revision='M-A.1', decision='accepted', evidence='【模拟】MES工艺包接收回执，固定总装图、作业指导书及测试限值')
        self.work = self.c('work-order', 'work_order.register', 'planner', order_line_id=self.order, revision_id=self.revision,
            source=self.source('work-order', 'work_order'), quantity=str(self.quantity), unit='台', purpose='production', trial_quantity='1',
            planned_start=self.at.isoformat(), planned_end=(self.at + timedelta(days=2)).isoformat())['object_id']
        self.c('allocate', 'order.allocate', 'planner', order_line_id=self.order, work_order_id=self.work, quantity=str(self.quantity), unit='台')
        for kind, label in [('equipment', 'DEMO-装配台与校准仪-03'), ('people', 'DEMO-模拟班组作业培训-A1')]:
            self.c('ready/' + kind, 'readiness.record', 'engineering', work_order_id=self.work, kind=kind, reference=label,
                evidence='【模拟】设备点检/培训证据由独立模拟工程身份验证，非实际员工资质', decision='verified', valid_until=(self.at + timedelta(days=90)).isoformat())
        self.lots = []
        for i, (material, owner) in enumerate(self.materials):
            lot = self.c('lot/' + str(i), 'material.define', 'supply', material_id='【模拟】' + material, lot_id='DEMO-' + self.key + '-LOT-' + str(i + 1), owner_id=owner, unit='件', scale=0,
                expiry=(self.at + timedelta(days=365)).date().isoformat(), source=self.source('lot/' + str(i), 'material_lot'))['object_id']
            self.lots.append(lot)
        requirements = [dict(work_order_id=self.work, execution_scope=scope, material_id='【模拟】' + material, owner_id=owner,
            quantity=str(1 if scope == 'trial' else self.quantity - 1), unit='件') for material, owner in self.materials for scope in ['trial', 'bulk']]
        plan = self.c('plan', 'plan.receive', 'planner', source=self.source('mrp-plan', 'plan'), input_revision_ids=[self.revision],
            input_order_versions=[dict(order_line_id=self.order, version=1)], requirements=requirements)['object_id']
        self.requirements = self.value('plan', plan)['requirement_ids']
        self.commitments = {}
        for i, req in enumerate(self.requirements):
            value = self.value('requirement', req)
            self.commitments[req] = self.c('commit/' + str(i), 'supply.commit', 'supply', requirement_id=req, type='customer' if value['owner_id'] == self.customer else 'purchase',
                owner_id=value['owner_id'], quantity=value['quantity'], unit='件', original_due=(self.at + timedelta(days=3)).date().isoformat(),
                current_due=(self.at + timedelta(days=5 if self.key == 'shortage' else 3)).date().isoformat(),
                source={**self.source('purchase/' + str(i), 'commitment'), 'evidence': '【模拟】' + ('客户客供料通知' if value['owner_id'] == self.customer else '栩川电子/临湾精工虚构供应商采购确认')})['object_id']
        self.c('units', 'unit.register', 'production', work_order_id=self.work, sns=['DEMO-' + self.key.upper() + '-' + str(i + 1).zfill(3) for i in range(self.quantity)])
        self.units = sorted(self.seed.objects(self.pid, 'unit'), key=lambda u: u['sn'])

    def stock(self):
        for i, lot in enumerate(self.lots):
            # Missing camera lenses and outstanding OEM purchased housings remain visible.
            if (self.key == 'shortage' and i == 1) or (self.oem and i == 1):
                continue
            value = self.value('material_lot', lot)
            for req in self.requirements:
                value_req = self.value('requirement', req)
                if value_req['material_id'] != value['material_id']:
                    continue
                external = 'DEMO-GRN-' + self.seed.ident(self.key + '/receipt/' + req)
                prefix = self.key + '/authority/' + req
                iqc = 'DEMO-IQC-' + self.seed.ident(prefix)
                self.seed.step(prefix + '/receive', 'receive', dict(project_id=self.pid, external_id=external,
                    commitment_id=self.commitments[req], lot_id=lot, material_id=value['material_id'], owner_id=value['owner_id'],
                    quantity=value_req['quantity'], unit='件', scale=0, expiry=value['expiry'], external_actor='【模拟】仓储系统收货员', signature='【模拟】虚构供应商送货单与仓库点收签收'))
                self.seed.step(prefix + '/inspect', 'inspect', dict(project_id=self.pid, external_id=iqc, receipt_external_id=external,
                    accepted=value_req['quantity'], rejected='0', external_actor='【模拟】来料检验系统', signature='【模拟】器件外观、型号与批次检验合格'))
                for kind, external_id, actor in [('receipt', external, 'supply'), ('iqc', iqc, 'quality')]:
                    self.c('pull/' + req + '/' + kind, 'source.pull', actor, system='erp', object_type=kind, external_id=external_id)
                result = self.c('reserve/' + req, 'reservation.request', 'planner', work_order_id=self.work, requirement_id=req, lot_id=lot, quantity=value_req['quantity'], unit='件')
                self.dispatch('reserve/' + req, result, 'planner')

    def dispatch(self, label, result, actor):
        self.c(label + '/dispatch', 'exchange.dispatch', actor, exchange_id=result['exchange_id'])
        exchange = self.value('exchange', result['exchange_id'])
        if exchange['phase'] != 'accepted':
            raise ValueError('Mock authority did not accept ' + label + ': ' + exchange['phase'])

    def start(self, units, mode):
        result = self.c('start/' + mode, 'production.start', 'production', work_order_id=self.work, mode=mode,
            unit_ids=[u['id'] for u in units], quantity=str(len(units)))
        self.dispatch('start/' + mode, result, 'production')

    def execute(self, unit, fail=False):
        uid = unit['id']
        source = self.source('execution/' + uid, 'execution')
        self.c('execution/' + uid, 'execution.record', 'production', work_order_id=self.work, sn=unit['sn'], station=self.route,
            route_version='DEMO-SOP-A.1', program_version='DEMO-TEST-A.1', firmware_version='DEMO-FW-1.4',
            material_uses=[dict(lot_id=lot, quantity='1', unit='件') for lot in self.lots], result='pass', occurred_at=source['occurred_at'], source=source)
        return self.c('test/' + uid, 'test.record', 'quality', unit_id=uid, attempt=1, program_version='DEMO-TEST-A.1', limit_version='DEMO-LIMIT-A.1', firmware_version='DEMO-FW-1.4',
            measurements=[{**self.limit, 'value': '5.42' if fail else '200' if self.printer else '5.02'}], source=self.source('test/' + uid, 'test'))['object_id']

    def production(self):
        self.start(self.units[:1], 'trial')
        test = self.execute(self.units[0], fail=self.key == 'quality')
        if self.key == 'quality':
            nc = self.c('ncr', 'nonconformance.open', 'quality', test_id=test, defect='【模拟】主电源输出5.42V超过5.15V上限，电源反馈分压电阻偏差', evidence='【模拟】保留原始失败测量；隔离该SN并评审返工路线')['object_id']
            self.c('rework', 'nonconformance.disposition', 'quality', nonconformance_id=nc, decision='rework', route_id='DEMO-RW-POWER-A1',
                route_steps=[dict(station='电源反馈电阻更换与复测', instruction_version='DEMO-RW-SOP-A1')], evidence='【模拟】独立质量身份批准返工，等待执行并保留失败历史')
            return
        if self.printer:
            return
        self.c('first-article', 'first_article.record', 'quality', work_order_id=self.work, unit_ids=[self.units[0]['id']], test_ids=[test], inspection_id='DEMO-FAI-' + self.key)
        self.start(self.units[1:], 'bulk')
        for unit in self.units[1:]:
            self.execute(unit)
        for kind, actor in [('manufacturing', 'production'), ('quality', 'quality')]:
            self.c('release/' + kind, 'release.decide', actor, kind=kind, unit_ids=[u['id'] for u in self.units], decision='approved', evidence='【模拟】' + ('生产完工与工艺记录核对' if kind == 'manufacturing' else '独立质量身份核对测试、追溯和首件证据后放行'))

    def delivery(self):
        units = self.units[:3] if self.key == 'partial' else self.units
        shipped = self.c('shipment', 'shipment.request', 'warehouse', order_line_id=self.order, unit_ids=[u['id'] for u in units], boxes=[], quantity=str(len(units)), unit='台')
        self.dispatch('shipment', shipped, 'warehouse')
        shipment = shipped['object_id']
        for action in ['sign', 'accept']:
            extra = {'issues': []} if action == 'accept' else {}
            self.c('delivery/' + action, 'delivery.' + action, 'warehouse', shipment_id=shipment, quantity=str(len(units)), source=self.source('delivery/' + action, 'delivery_' + action), external_signatory='【模拟】' + self.customer + '收货与验收代表', **extra)
        if self.key == 'aftercare':
            rma = self.c('rma', 'rma.open', 'quality', unit_id=units[0]['id'], shipment_id=shipment, reason='【模拟】现场反馈长线缆连接偶发掉帧，申请回厂分析；不撤销历史交付数量', source=self.source('rma', 'rma'))['object_id']
            self.c('capa', 'capa.update', 'quality', rma_id=rma, step='containment', description='【模拟】联系客户保留问题线缆与日志，安排同批产品排查', evidence='【模拟】临时遏制计划已记录，等待根因分析与纠正验证')


def populate(seed):
    for entry in PORTFOLIO:
        flow = Scenario(seed, entry)
        flow.foundation()
        flow.stock()
        if flow.key not in {'shortage', 'oem'}:
            flow.production()
        if flow.key in {'partial', 'aftercare'}:
            flow.delivery()
        if not any(p['key'] == flow.key for p in seed.manifest['projects']):
            seed.manifest['projects'].append(dict(key=flow.key, id=flow.pid, intended_stage=flow.stage))
            seed.checkpoint()
