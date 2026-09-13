/** 作者确认的设定事实与剧情事件，字段与后端 Story Bible 契约一致。 */
export interface StoryFact {
  id: number;
  novel_id: number;
  subject: string;
  attribute: string;
  value: string;
  description: string | null;
  chapter_established: number | null;
  status: 'active' | 'retired';
  retired_chapter: number | null;
  created_at: string;
  updated_at: string | null;
}

export type StoryFactCreate = Pick<StoryFact, 'novel_id' | 'subject' | 'attribute' | 'value'> &
  Partial<Pick<StoryFact, 'description' | 'chapter_established'>>;
export type StoryFactUpdate = Partial<Pick<StoryFact,
  'value' | 'description' | 'chapter_established' | 'status' | 'retired_chapter'>>;

export interface StoryEvent {
  id: number;
  novel_id: number;
  title: string;
  description: string;
  story_day: number;
  chapter: number | null;
  involved_characters: string[];
  foreshadowing: string | null;
  status: 'planned' | 'occurred';
  created_at: string;
  updated_at: string | null;
}

export type StoryEventCreate = Pick<StoryEvent, 'novel_id' | 'title' | 'description' | 'story_day'> &
  Partial<Pick<StoryEvent, 'chapter' | 'involved_characters' | 'foreshadowing' | 'status'>>;
export type StoryEventUpdate = Partial<Omit<StoryEventCreate, 'novel_id'>>;
