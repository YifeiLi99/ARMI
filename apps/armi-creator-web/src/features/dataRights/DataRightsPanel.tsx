import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiFailure,
  createDataRightsOrder,
  getDataRightsOrders,
} from "../../api/client";

type OrderKind = "stop_contact" | "stop_use" | "delete_related";

type DataRightsPanelProps = {
  token: string;
  environmentId: string;
  creatorPartyId: string;
  onUnauthorized: () => void;
};

const labels: Record<OrderKind, string> = {
  stop_contact: "停止联系",
  stop_use: "停止本地使用",
  delete_related: "删除相关本地数据",
};

export function DataRightsPanel({
  token,
  environmentId,
  creatorPartyId,
  onUnauthorized,
}: DataRightsPanelProps) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<OrderKind>("stop_contact");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const requestIdentity = useRef<{ kind: OrderKind; key: string } | null>(null);
  const queryKey = ["data-rights-orders", environmentId, creatorPartyId];
  const orders = useQuery({
    queryKey,
    queryFn: ({ signal }) => getDataRightsOrders(token, signal),
    retry: false,
  });
  const request = useMutation({
    mutationFn: async (orderKind: OrderKind) => {
      if (requestIdentity.current?.kind !== orderKind) {
        requestIdentity.current = {
          kind: orderKind,
          key: `creator-data-rights-${crypto.randomUUID()}`,
        };
      }
      return createDataRightsOrder(
        token,
        orderKind,
        requestIdentity.current.key,
      );
    },
    onSuccess: async (result) => {
      if (result.order_kind === "delete_related") {
        queryClient.removeQueries();
      }
      await queryClient.resetQueries({ queryKey, exact: true });
      setConfirmed(false);
      setMessage(
        result.order_kind === "delete_related"
          ? "删除命令已立即生效；下方列出逐项结算及仍保留的位置。"
          : `${labels[result.order_kind]}命令已立即生效。`,
      );
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.status === 401) {
        onUnauthorized();
        return;
      }
      setMessage("当前无法提交数据权利命令。");
    },
  });
  const resultOrders = Array.isArray(orders.data?.orders)
    ? orders.data.orders
    : null;

  return (
    <section className="authority-panel" aria-labelledby="data-rights-heading">
      <p className="eyebrow">Creator 数据权利</p>
      <h2 id="data-rights-heading">停止、删除与本地结算</h2>
      <form
        className="prompt-form"
        onSubmit={(event) => {
          event.preventDefault();
          setMessage(null);
          request.mutate(kind);
        }}
      >
        <label htmlFor="data-rights-kind">命令</label>
        <select
          id="data-rights-kind"
          value={kind}
          disabled={request.isPending}
          onChange={(event) => {
            setKind(event.currentTarget.value as OrderKind);
            setConfirmed(false);
          }}
        >
          {Object.entries(labels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <p className="field-note">
          命令按当前 Creator party
          立即生效，不提供撤销或恢复。删除只处理本机事实；共享来源和客观历史会如实保留。
        </p>
        {kind === "delete_related" ? (
          <label className="confirmation-row">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.currentTarget.checked)}
            />
            我确认执行不可撤销的本地删除
          </label>
        ) : null}
        <button
          type="submit"
          disabled={
            request.isPending || (kind === "delete_related" && !confirmed)
          }
        >
          {request.isPending ? "正在提交" : `执行${labels[kind]}`}
        </button>
      </form>
      {message === null ? null : <p role="status">{message}</p>}
      {orders.isLoading ? <p role="status">正在读取结算结果</p> : null}
      {orders.isError ? <p role="alert">当前无法读取数据权利结果。</p> : null}
      {orders.isSuccess && resultOrders === null ? (
        <p role="alert">数据权利结果格式无效。</p>
      ) : null}
      {resultOrders?.length === 0 ? <p>尚无数据权利命令。</p> : null}
      {resultOrders?.map((order) => (
        <article className="data-rights-order" key={order.order_id}>
          <h3>{labels[order.order_kind]}</h3>
          <dl>
            <div>
              <dt>请求方</dt>
              <dd>{order.requester_kind}</dd>
            </div>
            <div>
              <dt>命令状态</dt>
              <dd>{order.status}</dd>
            </div>
            <div>
              <dt>执行状态</dt>
              <dd>{order.execution_status}</dd>
            </div>
            <div>
              <dt>生效时间</dt>
              <dd>{order.effective_at}</dd>
            </div>
          </dl>
          {order.remaining_locations.length > 0 ? (
            <p>仍保留于：{order.remaining_locations.join("、")}</p>
          ) : null}
          <ol className="data-rights-timeline">
            {order.timeline.map((event, index) => (
              <li key={`${event.item_id ?? "order"}-${index}`}>
                <time dateTime={event.occurred_at}>{event.occurred_at}</time>
                <span>
                  {event.event_kind === "order_effective"
                    ? "命令生效"
                    : `项目 ${event.status}`}
                </span>
              </li>
            ))}
          </ol>
        </article>
      ))}
    </section>
  );
}
