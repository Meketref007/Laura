import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import API from '../api';
import { useTheme } from '../theme';

const STATUS_COLORS = {
  pending: '#f59e0b',
  processing: '#3b82f6',
  shipped: '#8b5cf6',
  delivered: '#22c55e',
  cancelled: '#ef4444',
  refunded: '#ef4444',
  failed: '#ef4444',
};

const STATUS_LABELS = {
  pending: 'Pending',
  processing: 'Processing',
  shipped: 'Shipped',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
  refunded: 'Refunded',
  failed: 'Failed',
};

function StatusBadge({ status, theme }) {
  const color = STATUS_COLORS[status?.toLowerCase()] || theme.textSecondary;
  const label = STATUS_LABELS[status?.toLowerCase()] || status || 'Unknown';
  return (
    <View style={[styles.badge, { backgroundColor: color + '20', borderColor: color }]}>
      <View style={[styles.badgeDot, { backgroundColor: color }]} />
      <Text style={[styles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

function OrderItem({ order, theme }) {
  return (
    <View style={[styles.orderCard, { backgroundColor: theme.card, borderColor: theme.border }]}>
      <View style={styles.orderHeader}>
        <Text style={[styles.orderId, { color: theme.text }]}>
          #{order.id || order.order_id || 'N/A'}
        </Text>
        <StatusBadge status={order.status} theme={theme} />
      </View>
      <View style={styles.orderDetails}>
        <Text style={[styles.orderCustomer, { color: theme.textSecondary }]}>
          {order.customer || order.customer_name || 'Unknown'}
        </Text>
        <Text style={[styles.orderTotal, { color: theme.text }]}>
          {order.total ? `$${Number(order.total).toFixed(2)}` : ''}
        </Text>
      </View>
      {order.items && (
        <Text style={[styles.orderItems, { color: theme.textSecondary }]}>
          {order.items} item{order.items !== 1 ? 's' : ''}
        </Text>
      )}
      {order.created_at && (
        <Text style={[styles.orderDate, { color: theme.textSecondary }]}>
          {new Date(order.created_at).toLocaleString()}
        </Text>
      )}
    </View>
  );
}

function SummaryBar({ data, theme }) {
  const total = data?.length || 0;
  const statusCounts = {};
  (data || []).forEach((o) => {
    const s = (o.status || 'unknown').toLowerCase();
    statusCounts[s] = (statusCounts[s] || 0) + 1;
  });

  return (
    <View style={[styles.summary, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <Text style={[styles.summaryTitle, { color: theme.text }]}>
        {total} Order{total !== 1 ? 's' : ''}
      </Text>
      <View style={styles.summaryRow}>
        {Object.entries(statusCounts).map(([status, count]) => (
          <View key={status} style={styles.summaryItem}>
            <View
              style={[
                styles.summaryDot,
                { backgroundColor: STATUS_COLORS[status] || theme.textSecondary },
              ]}
            />
            <Text style={[styles.summaryCount, { color: theme.textSecondary }]}>
              {count}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export default function OrdersScreen() {
  const theme = useTheme();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchOrders = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      const data = await API.get('api/status');
      const list = data?.orders || data?.recent_orders || [];
      setOrders(Array.isArray(list) ? list : []);
    } catch {
      setOrders([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchOrders();
    }, [fetchOrders])
  );

  if (loading && !refreshing) {
    return (
      <View style={[styles.center, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.accent} />
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      <SummaryBar data={orders} theme={theme} />
      <FlatList
        data={orders}
        keyExtractor={(item, index) => String(item.id || item.order_id || index)}
        renderItem={({ item }) => <OrderItem order={item} theme={theme} />}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => fetchOrders(true)}
            tintColor={theme.accent}
          />
        }
        ListEmptyComponent={
          <Text style={[styles.empty, { color: theme.textSecondary }]}>
            No orders found
          </Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  summary: {
    margin: 16,
    marginBottom: 0,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
  },
  summaryTitle: { fontSize: 16, fontWeight: '700', marginBottom: 8 },
  summaryRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  summaryItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  summaryDot: { width: 8, height: 8, borderRadius: 4 },
  summaryCount: { fontSize: 13, fontWeight: '600' },
  list: { padding: 16, paddingTop: 8 },
  orderCard: {
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    marginBottom: 10,
  },
  orderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  orderId: { fontSize: 15, fontWeight: '700' },
  orderDetails: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 2,
  },
  orderCustomer: { fontSize: 13 },
  orderTotal: { fontSize: 15, fontWeight: '600' },
  orderItems: { fontSize: 12, marginBottom: 2 },
  orderDate: { fontSize: 11, marginTop: 4 },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 20,
    borderWidth: 1,
    gap: 5,
  },
  badgeDot: { width: 6, height: 6, borderRadius: 3 },
  badgeText: { fontSize: 11, fontWeight: '600' },
  empty: { textAlign: 'center', marginTop: 40, fontSize: 15 },
});
