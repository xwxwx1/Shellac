"""Editor for a playlist Filter: a name regex plus tag rules (rules are OR'd, terms within one are AND'd)."""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core.filter import Filter, TagTerm

TermRole = Qt.ItemDataRole.UserRole + 1
EMPTY_TERM = '(empty — type a tag below and press Set Tag)'


class FilterDialog(QDialog):
    def __init__(self, parent=None, current: Filter | None = None, known_tags=()):
        super().__init__(parent)
        self.setWindowTitle('Filter')
        self.resize(520, 620)
        current = current or Filter()

        self.regex_edit = QLineEdit(current.regex)
        self.regex_edit.setPlaceholderText('e.g. ^Live|remix')
        self.regex_edit.textChanged.connect(self._validate_regex)
        self.regex_error = QLabel()
        self.regex_error.setStyleSheet('color: #e57373')
        self.strict_box = QCheckBox('Strict: song must match the regex AND the tag rules')
        self.strict_box.setChecked(current.strict)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.tree.currentItemChanged.connect(self._load_current_term)

        add_rule = QPushButton('Add Rule')
        add_rule.setToolTip('Ctrl+R — a new alternative (OR)')
        add_rule.clicked.connect(self.add_rule)
        add_tag = QPushButton('Add Tag')
        add_tag.setToolTip('Ctrl+T — another condition in this rule (AND)')
        add_tag.clicked.connect(self.add_term)
        delete = QPushButton('Delete')
        delete.setToolTip('Ctrl+Delete')
        delete.clicked.connect(self.delete_current)

        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText('Tag')
        self.tag_edit.setCompleter(QCompleter(list(known_tags), self))
        self.tag_edit.returnPressed.connect(self.set_term)
        self.negate_box = QCheckBox('Negate (NOT)')
        set_tag = QPushButton('Set Tag')
        set_tag.setToolTip('Ctrl+E')
        set_tag.clicked.connect(self.set_term)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Name matches regular expression:'))
        layout.addWidget(self.regex_edit)
        layout.addWidget(self.regex_error)
        layout.addWidget(self.strict_box)
        row = QHBoxLayout()
        for b in (add_rule, add_tag, delete):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        row.addWidget(self.tag_edit, 1)
        row.addWidget(self.negate_box)
        row.addWidget(set_tag)
        layout.addLayout(row)
        layout.addWidget(buttons)

        for keys, slot in (('Ctrl+R', self.add_rule), ('Ctrl+T', self.add_term),
                           ('Ctrl+Delete', self.delete_current), ('Ctrl+E', self.set_term),
                           ('Ctrl+N', self.negate_box.toggle),
                           ('Ctrl+Up', lambda: self._step(-1)), ('Ctrl+Down', lambda: self._step(1))):
            QShortcut(QKeySequence(keys), self, slot)

        for rule in current.rules:
            rule_item = self._new_rule()
            for term in rule:
                self._new_term(rule_item, term)
        self._refresh()
        self._validate_regex()

    # --- tree helpers ------------------------------------------------------------------------

    def _new_rule(self):
        item = QTreeWidgetItem()
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        return item

    def _new_term(self, rule_item, term=None):
        item = QTreeWidgetItem(rule_item)
        item.setData(0, TermRole, term)
        item.setText(0, str(term) if term else EMPTY_TERM)
        return item

    def _rule_of(self, item):
        return item if item is None or item.parent() is None else item.parent()

    def _refresh(self):
        texts = []
        for i in range(self.tree.topLevelItemCount()):
            rule = self.tree.topLevelItem(i)
            terms = [str(t) for t in (rule.child(j).data(0, TermRole) for j in range(rule.childCount())) if t]
            text = ' AND '.join(terms)
            rule.setText(0, text or '(empty rule)')
            if text:
                texts.append(text)
        self.summary.setText('Tags: ' + (' OR '.join(texts) or '(no rules: tags are not filtered)'))

    def _load_current_term(self, item, _previous=None):
        term = item.data(0, TermRole) if item is not None and item.parent() is not None else None
        if term:
            self.tag_edit.setText(term.tag)
            self.negate_box.setChecked(not term.required)

    def _step(self, delta):
        current = self.tree.currentItem()
        if current is None:
            return
        target = self.tree.itemBelow(current) if delta > 0 else self.tree.itemAbove(current)
        if target is not None:
            self.tree.setCurrentItem(target)

    # --- actions -----------------------------------------------------------------------------

    def add_rule(self):
        rule = self._new_rule()
        self.tree.setCurrentItem(self._new_term(rule))
        self._refresh()
        self.tag_edit.setFocus()

    def add_term(self):
        rule = self._rule_of(self.tree.currentItem())
        if rule is None:
            self.add_rule()
            return
        self.tree.setCurrentItem(self._new_term(rule))
        self._refresh()
        self.tag_edit.setFocus()

    def set_term(self):
        tag = self.tag_edit.text().strip()
        if not tag:
            return
        item = self.tree.currentItem()
        if item is None:
            self.add_rule()
            item = self.tree.currentItem()
        elif item.parent() is None:  # a rule is selected: fill its first empty term, or add one
            empty = [item.child(j) for j in range(item.childCount()) if not item.child(j).data(0, TermRole)]
            item = empty[0] if empty else self._new_term(item)
        term = TagTerm(tag, required=not self.negate_box.isChecked())
        item.setData(0, TermRole, term)
        item.setText(0, str(term))
        self.tree.setCurrentItem(item)
        self._refresh()

    def delete_current(self):
        item = self.tree.currentItem()
        if item is None:
            return
        rule = self._rule_of(item)
        if item is rule:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(rule))
        else:
            rule.removeChild(item)
            if rule.childCount() == 0:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(rule))
        self._refresh()

    # --- result ------------------------------------------------------------------------------

    def _validate_regex(self):
        try:
            re.compile(self.regex_edit.text())
        except re.error as e:
            self.regex_error.setText(f'Invalid regular expression: {e}')
            return False
        self.regex_error.setText('')
        return True

    def accept(self):
        if not self._validate_regex():
            QMessageBox.warning(self, 'Filter', self.regex_error.text())
            return
        super().accept()

    @property
    def filter(self) -> Filter:
        rules = []
        for i in range(self.tree.topLevelItemCount()):
            rule = self.tree.topLevelItem(i)
            rules.append([t for t in (rule.child(j).data(0, TermRole) for j in range(rule.childCount())) if t])
        return Filter(self.regex_edit.text(), rules, self.strict_box.isChecked())
