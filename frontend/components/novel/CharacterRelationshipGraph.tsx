'use client';

import { useMemo } from 'react';
import { Box, useTheme } from '@mui/material';
import type { CharacterResponse, CharacterRelationshipResponse } from '@/lib/api/generated/model';

interface CharacterRelationshipGraphProps {
  characters: CharacterResponse[];
  relationships: CharacterRelationshipResponse[];
}

interface GraphNode {
  id: number;
  x: number;
  y: number;
  name: string;
}

interface GraphEdge {
  key: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  labelX: number;
  labelY: number;
  label: string;
}

/**
 * 手绘 SVG 关系图（零图形依赖）：人物均匀排圆周，关系连线中点标注类型。
 * 人物是实体不是状态，色只用主题中性 token；不承诺缩放/拖拽等未实现的交互。
 */
export default function CharacterRelationshipGraph({ characters, relationships }: CharacterRelationshipGraphProps) {
  const theme = useTheme();

  const layout = useMemo(() => {
    const width = 480;
    const height = 300;
    const radius = characters.length <= 1 ? 0 : Math.min(110, 40 + characters.length * 14);
    const points = new Map<number, GraphNode>();
    characters.forEach((character, index) => {
      const angle = (index / characters.length) * Math.PI * 2 - Math.PI / 2;
      points.set(character.id, {
        id: character.id,
        x: width / 2 + radius * Math.cos(angle),
        y: height / 2 + radius * Math.sin(angle),
        name: character.name,
      });
    });
    const edges: GraphEdge[] = [];
    for (const relationship of relationships) {
      const a = points.get(relationship.character_a_id);
      const b = points.get(relationship.character_b_id);
      // 同一人物的自环不连线（数据允许 a=b，但一个圆点上无处可画）
      if (!a || !b || a === b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.hypot(dx, dy) || 1;
      const gap = 12;
      edges.push({
        key: relationship.id,
        x1: a.x + (dx / distance) * gap,
        y1: a.y + (dy / distance) * gap,
        x2: b.x - (dx / distance) * gap,
        y2: b.y - (dy / distance) * gap,
        labelX: (a.x + b.x) / 2,
        labelY: (a.y + b.y) / 2,
        label: relationship.relationship_type,
      });
    }
    return { width, height, nodes: Array.from(points.values()), edges };
  }, [characters, relationships]);

  if (layout.nodes.length === 0) return null;

  return <Box
    component="svg"
    role="img"
    aria-label={`人物关系图：${characters.length} 个人物，${relationships.length} 段关系`}
    viewBox={`0 0 ${layout.width} ${layout.height}`}
    sx={{ width: '100%', height: 'auto', display: 'block' }}
  >
    {layout.edges.map((edge) => <g key={edge.key}>
      <line x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2} stroke={theme.palette.divider} strokeWidth={1.5} />
      <text
        x={edge.labelX}
        y={edge.labelY}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={11}
        fill={theme.palette.text.secondary}
        stroke={theme.palette.background.paper}
        strokeWidth={4}
        paintOrder="stroke"
      >{edge.label}</text>
    </g>)}
    {layout.nodes.map((node) => <g key={node.id}>
      <circle cx={node.x} cy={node.y} r={6} fill={theme.palette.background.paper} stroke={theme.palette.text.primary} strokeWidth={1.5} />
      <text x={node.x} y={node.y + 22} textAnchor="middle" fontSize={12} fill={theme.palette.text.primary}>{node.name}</text>
    </g>)}
  </Box>;
}
