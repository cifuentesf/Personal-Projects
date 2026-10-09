import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

const distractionApps = ['Instagram', 'YouTube'];
const focusActions = [
  { label: 'Respirar 60s', detail: 'Pausa antes de abrir la app' },
  { label: 'Bloque 25 min', detail: 'Activa un sprint de enfoque' },
  { label: 'Escribir objetivo', detail: 'Define qué terminarás ahora' },
];

export default function App() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>NoScroll</Text>
        <Text style={styles.subtitle}>
          Menos Instagram/YouTube. Más progreso real.
        </Text>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Meta de hoy</Text>
          <Text style={styles.cardText}>Completar 3 bloques de enfoque antes de redes sociales.</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Apps que más distraen</Text>
          {distractionApps.map((app) => (
            <View key={app} style={styles.badge}>
              <Text style={styles.badgeText}>{app}</Text>
            </View>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Acción anti-procrastinación</Text>
          {focusActions.map((action) => (
            <TouchableOpacity key={action.label} style={styles.actionButton} activeOpacity={0.85}>
              <Text style={styles.actionLabel}>{action.label}</Text>
              <Text style={styles.actionDetail}>{action.detail}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0B1020',
  },
  container: {
    paddingHorizontal: 20,
    paddingVertical: 24,
    gap: 16,
  },
  title: {
    color: '#F8FAFC',
    fontSize: 34,
    fontWeight: '800',
  },
  subtitle: {
    color: '#CBD5E1',
    fontSize: 16,
    lineHeight: 22,
    marginBottom: 8,
  },
  card: {
    backgroundColor: '#111A2F',
    borderRadius: 16,
    padding: 16,
    gap: 10,
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  cardTitle: {
    color: '#E2E8F0',
    fontSize: 18,
    fontWeight: '700',
  },
  cardText: {
    color: '#94A3B8',
    fontSize: 15,
    lineHeight: 20,
  },
  badge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: '#1D4ED8',
  },
  badgeText: {
    color: '#EFF6FF',
    fontWeight: '700',
  },
  actionButton: {
    backgroundColor: '#172554',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#1E40AF',
  },
  actionLabel: {
    color: '#DBEAFE',
    fontSize: 16,
    fontWeight: '700',
  },
  actionDetail: {
    color: '#BFDBFE',
    fontSize: 13,
    marginTop: 3,
  },
});
