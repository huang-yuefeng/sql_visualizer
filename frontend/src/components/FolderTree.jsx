import React from 'react';

export default function FolderTree({ tree, selected, onSelectionChange, indexed }) {
  if (!tree) return null;

  const toggle = (path) => {
    if (selected.includes(path)) {
      onSelectionChange(selected.filter(p => p !== path));
    } else {
      onSelectionChange([...selected, path]);
    }
  };

  const toggleAll = () => {
    const all = collectAll(tree);
    if (selected.length === all.length) onSelectionChange([]);
    else onSelectionChange(all);
  };

  const allSql = collectAll(tree);
  const allSelected = selected.length === allSql.length && allSql.length > 0;

  return (
    <div className="folder-tree">
      <h3>
        Files
        {allSql.length > 0 && (
          <span className="select-all" onClick={toggleAll}>
            {allSelected ? '[deselect all]' : '[select all]'}
          </span>
        )}
      </h3>
      <div className="tree-list">
        <TreeNode node={tree} selected={selected} onToggle={toggle} depth={0} />
      </div>
      {indexed && (
        <div className="index-status">Indexed {selected.length} scripts</div>
      )}
    </div>
  );
}

function TreeNode({ node, selected, onToggle, depth }) {
  const isSql = node.type === 'file' && node.is_sql;
  const isNonSql = node.type === 'file' && !node.is_sql;
  const checked = isSql && selected.includes(node.path);

  return (
    <div>
      <div className={`tree-node depth-${depth} ${isNonSql ? 'non-sql' : ''}`}
        style={{ paddingLeft: depth * 16 + 4 }}>
        {node.type === 'directory' && <span className="tree-icon">{"📁"}</span>}
        {isSql && (
          <label>
            <input type="checkbox" checked={checked || false}
              onChange={() => onToggle(node.path)} />
            {"📄"} {node.name}
          </label>
        )}
        {isNonSql && <span>{"📄"} {node.name}</span>}
        {node.type === 'directory' && <span>{node.name}</span>}
      </div>
      {node.children && node.children.map((c, i) => (
        <TreeNode key={i} node={c} selected={selected} onToggle={onToggle} depth={depth + 1} />
      ))}
    </div>
  );
}

function collectAll(tree) {
  const paths = [];
  if (tree.type === 'file' && tree.is_sql) paths.push(tree.path);
  if (tree.children) tree.children.forEach(c => paths.push(...collectAll(c)));
  return paths;
}
