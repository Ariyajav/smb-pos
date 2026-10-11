import requests
import logging
from odoo import fields, api, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductClassificationBuna(models.Model):
    _name = 'product.classification.buna'
    _description = 'BUNA Classification Cache'
    # 16.0 used a stored ``display_name`` as _rec_name. 17+ cannot store
    # display_name, so _rec_name is ``name`` and the "[code] name" label is a
    # regular (non-stored) _compute_display_name; name_search matches code or
    # name. The old ``display_name`` column stays in the table, unused.
    _rec_name = 'name'
    _rec_names_search = ['code', 'name']

    level = fields.Selection([
        ('sector', 'Салбар'),
        ('subsector', 'Дэд салбар'),
        ('group', 'Бүлэг'),
        ('class', 'Анги'),
        ('subclass', 'Дэд анги'),
        ('detail', 'Нарийвчилсан анги'),
        ('buna_code', 'БҮНА код')
    ], required=True)
    
    code = fields.Char('Code', required=True)
    name = fields.Char('Name', required=True)
    parent_id = fields.Many2one('product.classification.buna', 'Parent')
    child_ids = fields.One2many('product.classification.buna', 'parent_id', 'Children')
    
    # API параметрүүд
    p1 = fields.Char('P1 (Sector)')
    p2 = fields.Char('P2 (Subsector)')
    p3 = fields.Char('P3 (Group)')
    p4 = fields.Char('P4 (Class)')
    p5 = fields.Char('P5 (Subclass)')
    p6 = fields.Char('P6 (BUNA Code)')
    
    cached_at = fields.Datetime('Cached At', default=fields.Datetime.now)
    has_children = fields.Boolean('Has Children', default=False)
    
    # Баркодын мэдээлэл (зөвхөн БҮНА код түвшинд)
    barcode_ids = fields.One2many('product.barcode.buna', 'classification_id', 'Barcodes')
    barcode_count = fields.Integer('Barcode Count', compute='_compute_barcode_count')

    @api.depends('code', 'name', 'level')
    def _compute_display_name(self):
        for record in self:
            if record.level == 'sector':
                record.display_name = f"[{record.code}] {record.name}"
            else:
                record.display_name = f"[{record.code}] {record.name}"

    @api.depends('barcode_ids')
    def _compute_barcode_count(self):
        for record in self:
            record.barcode_count = len(record.barcode_ids)

    def _get_api_url(self):
        """API URL үүсгэх"""
        base_url = "https://api.ebarimt.mn/api/info/check/barcode/v2"
        
        # Параметрүүдийг цуглуулах
        params = [self.p1 or '', self.p2 or '', self.p3 or '', self.p4 or '', self.p5 or '', self.p6 or '']
        
        # Хоосон параметрүүдийг арилгах
        while params and not params[-1]:
            params.pop()
        
        if params:
            return f"{base_url}/{'/'.join(params)}"
        else:
            return base_url

    @api.model
    def _fetch_from_api(self, p1='', p2='', p3='', p4='', p5='', p6=''):
        """eBarimt API-аас мэдээлэл татах"""
        # The parameters become URL path segments: codes only, no '/' or '..'.
        if any(p and not str(p).isalnum() for p in (p1, p2, p3, p4, p5, p6)):
            return {'success': False, 'error': 'Invalid classification code'}
        try:
            # URL үүсгэх
            base_url = "https://api.ebarimt.mn/api/info/check/barcode/v2"
            params = [p1, p2, p3, p4, p5, p6]
            
            # Хоосон параметрүүдийг арилгах
            while params and not params[-1]:
                params.pop()
            
            if params:
                url = f"{base_url}/{'/'.join(params)}"
            else:
                url = base_url
            
            _logger.info(f"BUNA API хүсэлт: {url}")
            
            headers = {'Accept': 'application/json'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            _logger.info(f"BUNA API хариу авлаа: {len(data)} өгөгдөл")
            
            return {'success': True, 'data': data}
            
        except requests.RequestException as e:
            _logger.error(f"BUNA API алдаа: {e}")
            return {'success': False, 'error': str(e)}

    def _determine_next_level(self):
        """Дараагийн түвшинг тодорхойлох"""
        level_map = {
            'sector': 'subsector',
            'subsector': 'group', 
            'group': 'class',
            'class': 'subclass',
            'subclass': 'detail',
            'detail': 'buna_code'
        }
        return level_map.get(self.level)

    def _create_child_records(self, api_data):
        """API өгөгдлөөс хүүхэд бичлэгүүд үүсгэх"""
        next_level = self._determine_next_level()
        if not next_level:
            return []
        
        created_records = []
        
        for item in api_data:
            if isinstance(item, list) and len(item) >= 2:
                code = item[0]
                name = item[1]
                
                path = self._buna_path(str(code))
                new_params = {'p%d' % (i + 1): path[i] if i < len(path) else '' for i in range(6)}

                # Одоо байгаа эсэхийг шалгах
                existing = self.search([
                    ('code', '=', code),
                    ('level', '=', next_level),
                    ('parent_id', '=', self.id)
                ])
                
                if not existing:
                    vals = {
                        'code': code,
                        'name': name,
                        'level': next_level,
                        'parent_id': self.id,
                        **new_params
                    }
                    
                    record = self.create(vals)
                    created_records.append(record)
                    _logger.info(f"BUNA бичлэг үүсгэлээ: [{code}] {name}")
                else:
                    created_records.append(existing)
        
        return created_records

    def action_load_children(self):
        """Хүүхэд бичлэгүүдийг API-аас татах"""
        self.ensure_one()
        
        # Баркод түвшинд хүрсэн бол баркод татах
        if self.level == 'buna_code':
            return self.action_load_barcodes()
        
        # API-аас мэдээлэл татах
        result = self._fetch_from_api(self.p1, self.p2, self.p3, self.p4, self.p5, self.p6)
        
        if not result['success']:
            raise ValidationError(f"API алдаа: {result['error']}")
        
        # Хүүхэд бичлэгүүд үүсгэх
        children = self._create_child_records(result['data'])
        
        # Has children шинэчлэх
        self.has_children = len(children) > 0
        
        # Tree view-г шинэчлэн нээх - ШИНЭ ХЭСЭГ
        return {
            'type': 'ir.actions.act_window',
            'name': 'БҮНА Classifications',
            'res_model': 'product.classification.buna',
            'view_mode': 'list,form',
            'domain': [('parent_id', '=', self.id)],  # Зөвхөн хүүхдүүдийг харуулах
            'context': {
                'default_parent_id': self.id,
                'search_default_parent_id': self.id
            },
            'target': 'current'  # Яг ижил цонхонд нээх
        }

    def action_load_barcodes(self):
        """Баркодуудыг API-аас татах"""
        self.ensure_one()
        
        if self.level != 'buna_code':
            raise ValidationError("Зөвхөн БҮНА код түвшинд баркод татах боломжтой")
        
        # API-аас баркод мэдээлэл татах
        result = self._fetch_from_api(self.p1, self.p2, self.p3, self.p4, self.p5, self.p6)
        
        if not result['success']:
            raise ValidationError(f"API алдаа: {result['error']}")
        
        # Одоо байгаа баркодуудыг устгах
        self.barcode_ids.unlink()
        
        # Шинэ баркодууд үүсгэх
        barcode_count = 0
        for item in result['data']:
            if isinstance(item, list) and len(item) >= 2:
                barcode = item[0]
                description = item[1] if len(item) > 1 else ''
                
                self.env['product.barcode.buna'].create({
                    'classification_id': self.id,
                    'barcode': barcode,
                    'description': description
                })
                barcode_count += 1
        
        _logger.info(f"БҮНА баркод татагдлаа: {barcode_count}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Амжилттай'),
                'message': _('%d баркод татагдлаа') % barcode_count,
                'type': 'success'
            }
        }

    # BUNA codes are hierarchical: each level adds one digit to its parent's
    # code (6 > 61 > 611 > 6118 > 61184 > 61184xx). A product uses a full
    # 7-digit code.
    BUNA_LEVELS = ['sector', 'subsector', 'group', 'class', 'subclass', 'detail']
    BUNA_CODE_LENGTH = 7

    @api.model
    def _buna_path(self, code):
        """API path (p1..p6) of a code: the codes of its ancestors and itself."""
        return [code[:i] for i in range(1, min(len(code), 5) + 1)] + ([code] if len(code) > 5 else [])

    @api.model
    def _buna_node(self, code, name, parent):
        path = self._buna_path(code)
        vals = {
            'code': code,
            'name': name,
            'level': self.BUNA_LEVELS[len(path) - 1],
            'parent_id': parent.id if parent else False,
            **{'p%d' % (i + 1): path[i] if i < len(path) else False for i in range(6)},
        }
        node = self.search([('code', '=', code)], limit=1)
        if node:
            node.write(vals)
        else:
            node = self.create(vals)
        return node

    @api.model
    def _buna_children(self, code=''):
        """[(code, name), ...] that eBarimt lists under ``code``."""
        result = self._fetch_from_api(*self._buna_path(code)) if code else self._fetch_from_api()
        if not result['success']:
            raise ValidationError(_("eBarimt BUNA API error: %s", result['error']))
        return [(str(item[0]), item[1]) for item in result['data']
                if isinstance(item, (list, tuple)) and len(item) >= 2]

    @api.model
    def load_code_subtree(self, code):
        """Load ``code`` (for example subclass 61184 or class 9591) with its
        ancestors and every code under it, down to the 7-digit codes products
        use. Returns the number of 7-digit codes loaded."""
        code = (code or '').strip()
        if not code.isdigit() or not 1 <= len(code) <= self.BUNA_CODE_LENGTH:
            raise ValidationError(_("\"%s\" is not a BUNA code (1-7 digits).", code))
        path = self._buna_path(code)
        parent = self.browse()
        for depth, step in enumerate(path):
            names = dict(self._buna_children(path[depth - 1] if depth else ''))
            if step not in names:
                raise ValidationError(_("eBarimt has no BUNA code %s.", step))
            parent = self._buna_node(step, names[step], parent)
        return self._load_below(parent)

    def _load_below(self, node):
        if len(node.code) >= self.BUNA_CODE_LENGTH:
            return 1
        children = self._buna_children(node.code)
        node.has_children = bool(children)
        count = 0
        for code, name in children:
            count += self._load_below(self._buna_node(code, name, node))
        return count

    @api.model
    def get_or_create_sector_list(self):
        """Салбарын жагсаалтыг авах эсвэл үүсгэх"""
        # Салбарууд байгаа эсэхийг шалгах
        sectors = self.search([('level', '=', 'sector')])
        
        if not sectors:
            # API-аас салбаруудыг татах
            result = self._fetch_from_api()
            
            if result['success']:
                for item in result['data']:
                    if isinstance(item, list) and len(item) >= 2:
                        code = item[0]
                        name = item[1]
                        
                        self.create({
                            'code': code,
                            'name': name,
                            'level': 'sector',
                            'p1': code,
                            'has_children': True
                        })
                
                sectors = self.search([('level', '=', 'sector')])
                _logger.info(f"БҮНА салбарууд үүсгэгдлээ: {len(sectors)}")
        
        return sectors

    @api.model
    def search_classification_by_name(self, name, limit=10):
        """Нэрээр ангилал хайх"""
        return self.search([
            ('name', 'ilike', name)
        ], limit=limit)

    def get_full_path(self):
        """Бүтэн замыг авах (Салбар > Дэд салбар > ...)"""
        self.ensure_one()
        path = []
        current = self
        
        while current:
            path.append(f"[{current.code}] {current.name}")
            current = current.parent_id
        
        return " > ".join(reversed(path))


class ProductBarcodeBuna(models.Model):
    _name = 'product.barcode.buna'
    _description = 'BUNA Barcode Information'

    classification_id = fields.Many2one('product.classification.buna', 'Classification', required=True, ondelete='cascade')
    barcode = fields.Char('Barcode', required=True)
    description = fields.Text('Description')
    
    _unique_barcode_classification = models.Constraint(
        'unique(classification_id, barcode)',
        'Barcode must be unique within classification!',
    )

    @api.depends('barcode', 'description')
    def _compute_display_name(self):
        for record in self:
            name = f"{record.barcode}"
            if record.description:
                name += f" - {record.description[:50]}"
            record.display_name = name