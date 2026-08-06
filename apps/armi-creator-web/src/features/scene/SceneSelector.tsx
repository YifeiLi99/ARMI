import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";

import {
  ApiFailure,
  createCreatorScene,
  getCreatorScenes,
  setCreatorSceneOpen,
} from "../../api/client";
import type { CreatorScene } from "../../api/client";

type SceneSelectorProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  selectedSceneKey: string;
  onSelected: (sceneKey: string, status: "open" | "closed") => void;
  onUnauthorized: () => void;
};

const SCENE_KEY = /^[a-z0-9][a-z0-9._-]{0,63}$/;

export function SceneSelector({
  token,
  environmentId,
  creatorPartyId,
  selectedSceneKey,
  onSelected,
  onUnauthorized,
}: SceneSelectorProps) {
  const queryClient = useQueryClient();
  const [managing, setManaging] = useState(false);
  const [newSceneKey, setNewSceneKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const queryKey = ["creator-scenes", environmentId, creatorPartyId] as const;
  const scenes = useQuery({
    queryKey,
    queryFn: ({ signal }) => getCreatorScenes(token, signal),
    enabled: managing,
    retry: false,
  });

  function handleFailure(error: unknown): void {
    if (error instanceof ApiFailure && error.status === 401) {
      onUnauthorized();
      return;
    }
    setMessage(
      error instanceof ApiFailure && error.status === 409
        ? "这个场合标识已经存在。"
        : "Runtime 未能完成场合操作。",
    );
  }

  const createScene = useMutation({
    mutationFn: (sceneKey: string) => createCreatorScene(token, sceneKey),
    onSuccess: async (scene) => {
      setNewSceneKey("");
      setMessage("新场合已建立。");
      await queryClient.invalidateQueries({ queryKey, exact: true });
      onSelected(scene.scene_key, scene.status);
    },
    onError: handleFailure,
  });
  const transition = useMutation({
    mutationFn: ({ scene, open }: { scene: CreatorScene; open: boolean }) =>
      setCreatorSceneOpen(token, scene.scene_key, open),
    onSuccess: async (scene) => {
      setMessage(scene.status === "open" ? "场合已重新打开。" : "场合已关闭。");
      await queryClient.invalidateQueries({ queryKey, exact: true });
      onSelected(scene.scene_key, scene.status);
    },
    onError: handleFailure,
  });

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const key = newSceneKey.trim();
    if (!SCENE_KEY.test(key) || key === "default") {
      setMessage("场合标识须为小写字母或数字开头，并只包含 . _ -。 ");
      return;
    }
    setMessage(null);
    createScene.mutate(key);
  }

  const selected = scenes.data?.scenes?.find(
    (scene) => scene.scene_key === selectedSceneKey,
  );

  if (!managing) {
    return (
      <section
        className="scene-selector"
        aria-labelledby="scene-selector-heading"
      >
        <div className="panel-heading-row">
          <div>
            <p className="eyebrow">Creator 场合</p>
            <h2 id="scene-selector-heading">{selectedSceneKey}</h2>
          </div>
          <button
            type="button"
            className="secondary"
            onClick={() => setManaging(true)}
          >
            管理场合
          </button>
        </div>
        <p className="boundary-note">
          当前输入、timeline 与事件流都绑定到这个场合。
        </p>
      </section>
    );
  }

  return (
    <section
      className="scene-selector"
      aria-labelledby="scene-selector-heading"
    >
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">Creator 场合</p>
          <h2 id="scene-selector-heading">当前场合</h2>
        </div>
        {selected && !selected.is_default ? (
          <button
            type="button"
            className="secondary"
            disabled={transition.isPending}
            onClick={() =>
              transition.mutate({
                scene: selected,
                open: selected.status === "closed",
              })
            }
          >
            {selected.status === "open" ? "关闭场合" : "重新打开"}
          </button>
        ) : null}
        <button
          type="button"
          className="secondary"
          onClick={() => setManaging(false)}
        >
          收起
        </button>
      </div>
      {scenes.isPending ? <p role="status">正在读取场合…</p> : null}
      {scenes.isError ? <p role="alert">当前无法读取 Creator 场合。</p> : null}
      {scenes.data ? (
        <label>
          场合
          <select
            value={selectedSceneKey}
            onChange={(event) => {
              const next = scenes.data.scenes.find(
                (scene) => scene.scene_key === event.currentTarget.value,
              );
              if (next) {
                setMessage(null);
                onSelected(next.scene_key, next.status);
              }
            }}
          >
            {(scenes.data.scenes ?? []).map((scene) => (
              <option key={scene.scene_id} value={scene.scene_key}>
                {scene.scene_key}
                {scene.status === "closed" ? "（已关闭）" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <form className="scene-create-form" onSubmit={submit}>
        <label htmlFor="new-scene-key">新场合标识</label>
        <div>
          <input
            id="new-scene-key"
            value={newSceneKey}
            autoComplete="off"
            spellCheck={false}
            maxLength={64}
            placeholder="例如：night-talk"
            onChange={(event) => setNewSceneKey(event.currentTarget.value)}
          />
          <button type="submit" disabled={createScene.isPending}>
            建立场合
          </button>
        </div>
      </form>
      {message ? <p role="status">{message}</p> : null}
      <p className="boundary-note">
        每个场合只携带自己的近期往来；跨场连续性来自同一个主体的记忆、关系和活动。
      </p>
    </section>
  );
}
